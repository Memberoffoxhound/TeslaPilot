#!/usr/bin/env python3
import json
import os
import re
import time
from pathlib import Path

# D-Bus type signature, used to unwrap (sig, value) variants from GetManagedObjects
_SIG = re.compile(r"^[ybnqiuxtdhsovgae(){}[\]]+$")

# AVRCP now-playing for the mici UI. Metadata comes from BlueZ MediaPlayer1 on the
# system bus. Cover art is optional (needs BlueZ 5.79+ BIP); a missing file is a
# placeholder, not an error. State lives on tmpfs so 1 Hz position is not written to /data.
# The UI never talks to D-Bus: it writes a one-word command on tmpfs, and this process
# calls Play/Pause/Next/Previous, debounced and ignored while engaged.

STATE_PATH = "/dev/shm/dpbridge-nowplaying.json"
ART_PREFIX = "/dev/shm/dpbridge-art"
ART_STAGING = "/dev/shm/dpbridge-art.d"
OBEX = "org.bluez.obex"
ART_RETRY_S = 15.0
CMD_PATH = "/dev/shm/dpbridge-nowplaying.cmd"
PLAYER_IF = "org.bluez.MediaPlayer1"
TRANSPORT_IF = "org.bluez.MediaTransport1"
POLL_S = 1.0
DEBOUNCE_S = 0.4
COMMANDS = frozenset({"play", "pause", "next", "previous"})
METHODS = {"play": "Play", "pause": "Pause", "next": "Next", "previous": "Previous"}
VISIBLE_STATUS = frozenset({"playing", "paused", "forward-seek", "reverse-seek", "error"})
EMPTY = {
  "status": "", "title": "", "artist": "", "album": "",
  "duration_ms": 0, "position_ms": 0, "art": None,
  "stream": "", "error": "",
}

# A2DP codec IDs (A2DP 1.3)
CODEC_SBC, CODEC_MPEG, CODEC_AAC, CODEC_ATRAC, CODEC_VENDOR = 0x00, 0x01, 0x02, 0x04, 0xFF
# bit index in each A2DP field (bit 0 is the low bit of that field)
SBC_FREQ = {3: 16000, 2: 32000, 1: 44100, 0: 48000}
SBC_CHAN = {3: "mono", 2: "dual", 1: "stereo", 0: "joint"}
SBC_BLOCKS = {3: 4, 2: 8, 1: 12, 0: 16}
SBC_SUBBANDS = {1: 4, 0: 8}


def fmt_mmss(ms) -> str:
  try:
    n = int(ms)
  except (TypeError, ValueError):
    return "--:--"
  if n < 0 or n >= 0xFFFFFFFF:
    return "--:--"
  s = n // 1000
  return f"{s // 60}:{s % 60:02d}"


def unwrap(value):
  # GetManagedObjects leaves variants as (signature, value). Signatures can be
  # "s" or "a{sv}"; a 2-tuple whose first item is not a signature is left alone.
  if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str) and _SIG.fullmatch(value[0]):
    return unwrap(value[1])
  if isinstance(value, dict):
    return {k: unwrap(v) for k, v in value.items()}
  return value


def track_state(track, status: str, position_ms, art=None, stream="", error="") -> dict:
  t = unwrap(track) or {}
  try:
    duration_ms = int(t["Duration"]) if t.get("Duration") is not None else 0
  except (TypeError, ValueError):
    duration_ms = 0
  try:
    pos = int(unwrap(position_ms))
  except (TypeError, ValueError):
    pos = 0
  if duration_ms >= 0xFFFFFFFF:
    duration_ms = 0
  return {
    "status": status or "",
    "title": str(t.get("Title") or "").strip(),
    "artist": str(t.get("Artist") or "").strip(),
    "album": str(t.get("Album") or "").strip(),
    "duration_ms": duration_ms,
    "position_ms": pos,
    "art": art,
    "stream": stream or "",
    "error": error or "",
  }


def visible(state: dict) -> bool:
  if not state:
    return False
  if state.get("error") and (state.get("title") or state.get("artist") or state.get("album") or state.get("status")):
    return True
  if state.get("status") not in VISIBLE_STATUS:
    return False
  return bool(state.get("title") or state.get("artist") or state.get("album"))


def write_state(state: dict, path: str | None = None):
  p = Path(STATE_PATH if path is None else path)
  tmp = p.with_name(p.name + ".tmp")
  tmp.write_text(json.dumps(state, separators=(",", ":")))
  os.replace(tmp, p)


def read_state(path: str | None = None) -> dict:
  try:
    return json.loads(Path(STATE_PATH if path is None else path).read_text())
  except (OSError, json.JSONDecodeError, TypeError, ValueError):
    return {}


def parse_command(raw) -> str | None:
  cmd = str(raw or "").strip().lower()
  return cmd if cmd in COMMANDS else None


def send_command(cmd: str, path: str | None = None) -> bool:
  cmd = parse_command(cmd)
  if not cmd:
    return False
  p = Path(CMD_PATH if path is None else path)
  tmp = p.with_name(p.name + ".tmp")
  tmp.write_text(cmd)
  os.replace(tmp, p)
  return True


def take_command(path: str | None = None) -> str | None:
  p = Path(CMD_PATH if path is None else path)
  try:
    raw = p.read_text()
    p.unlink(missing_ok=True)
  except OSError:
    return None
  return parse_command(raw)


def accept_command(cmd, engaged, now, last_cmd, last_t, debounce_s=DEBOUNCE_S):
  # drop unknown, engaged, and bursts; always consume the file first (caller does that)
  if not cmd or engaged:
    return None, last_cmd, last_t
  if last_t is not None and (now - last_t) < debounce_s:
    return None, last_cmd, last_t
  return cmd, cmd, now


def find_player(objects: dict) -> str | None:
  for path, ifs in (objects or {}).items():
    if PLAYER_IF in ifs:
      return path
  return None


def props(objects: dict, path: str, iface: str) -> dict:
  return unwrap((objects or {}).get(path, {}).get(iface, {})) or {}


def _cfg_bytes(config) -> bytes:
  config = unwrap(config)
  if isinstance(config, (bytes, bytearray)):
    return bytes(config)
  if isinstance(config, (list, tuple)):
    try:
      return bytes(int(x) & 0xFF for x in config)
    except (TypeError, ValueError):
      return b""
  return b""


def _sbc_pick_max(bits, table):
  # negotiated config usually has one bit set; if several (capabilities), take the best
  found = [table[i] for i in table if bits & (1 << i)]
  return max(found) if found else None


def sbc_params(config) -> dict | None:
  raw = _cfg_bytes(config)
  if len(raw) < 4:
    return None
  freq = _sbc_pick_max(raw[0] >> 4, SBC_FREQ)
  mode = next((SBC_CHAN[i] for i in (0, 1, 2, 3) if (raw[0] & 0x0F) & (1 << i)), None)
  blocks = _sbc_pick_max(raw[1] >> 4, SBC_BLOCKS)
  subbands = _sbc_pick_max((raw[1] >> 2) & 0x03, SBC_SUBBANDS)
  if not freq or mode is None or not blocks or not subbands:
    return None
  bitpool = max(raw[2], raw[3])
  return {"freq": freq, "channels": 1 if mode == "mono" else 2, "mode": mode,
          "blocks": blocks, "subbands": subbands, "bitpool": bitpool}


def sbc_bitrate_kbps(config) -> int | None:
  # A2DP 1.3 section 12.9: bit_rate = 8 * frame_length * fs / (subbands * blocks)
  p = sbc_params(config)
  if p is None or p["bitpool"] <= 0:
    return None
  ch, sb, bl, bp = p["channels"], p["subbands"], p["blocks"], p["bitpool"]
  header = 4 + (4 * sb * ch) // 8
  if p["mode"] == "mono" or p["mode"] == "dual":
    payload = (bl * ch * bp + 7) // 8
  elif p["mode"] == "joint":
    payload = (sb + bl * bp + 7) // 8
  else:
    payload = (bl * bp + 7) // 8
  frame = header + payload
  return max(1, round(8 * frame * p["freq"] / (sb * bl) / 1000))


def aac_bitrate_kbps(config) -> int | None:
  # A2DP AAC: VBR flag plus a 23-bit peak bitrate in the last octets
  raw = _cfg_bytes(config)
  if len(raw) < 5:
    return None
  if len(raw) >= 6:
    bps = ((raw[3] & 0x7F) << 16) | (raw[4] << 8) | raw[5]
    if bps == 0:
      bps = ((raw[2] & 0x3F) << 16) | (raw[3] << 8) | raw[4]
  else:
    bps = ((raw[2] & 0x3F) << 16) | (raw[3] << 8) | raw[4]
  if bps <= 0:
    return None
  return max(1, round(bps / 1000))


def stream_label(codec, config) -> str:
  try:
    codec = int(unwrap(codec))
  except (TypeError, ValueError):
    return ""
  kbps = None
  if codec == CODEC_SBC:
    name, kbps = "SBC", sbc_bitrate_kbps(config)
  elif codec == CODEC_AAC:
    name, kbps = "AAC", aac_bitrate_kbps(config)
  elif codec == CODEC_MPEG:
    name = "MPEG"
  elif codec == CODEC_ATRAC:
    name = "ATRAC"
  elif codec == CODEC_VENDOR:
    name = "vendor"
  else:
    name = f"codec {codec}"
  return f"{name} ~{kbps} kbps" if kbps else name


def find_transport(objects: dict, device=None) -> tuple[str | None, dict]:
  for path, ifs in (objects or {}).items():
    if TRANSPORT_IF not in ifs:
      continue
    p = props(objects, path, TRANSPORT_IF)
    if device and p.get("Device") and unwrap(p.get("Device")) != unwrap(device):
      continue
    return path, p
  return None, {}


def error_line(status, transport_state, has_transport, aplay_running, control_error=False) -> str:
  if control_error:
    return "control failed"
  if status == "error":
    return "player error"
  playing = status in ("playing", "forward-seek", "reverse-seek")
  if not playing:
    return ""
  if not has_transport:
    return "no A2DP transport"
  if transport_state in (None, "", "idle"):
    return "transport idle"
  if transport_state == "pending":
    return "transport pending"
  if not aplay_running:
    return "aplay not running"
  return ""


def aplay_is_running() -> bool:
  try:
    for name in os.listdir("/proc"):
      if not name.isdigit():
        continue
      try:
        if Path(f"/proc/{name}/comm").read_text().strip() == "bluealsa-aplay":
          return True
      except OSError:
        continue
  except OSError:
    pass
  return False
def art_path(handle: str, prefix: str = ART_PREFIX) -> str:
  # one file per handle so the UI reloads its texture on a new track
  return f"{prefix}-{re.sub(r'[^0-9A-Za-z]', '', handle)[:16] or 'x'}.jpg"


def _obex_conn():
  from jeepney.io.blocking import open_dbus_connection
  return open_dbus_connection(bus="SYSTEM")


def _wait_transfer(conn, path: str, timeout: float, sleep=time.sleep, clock=time.monotonic) -> str:
  from jeepney import DBusAddress, Properties
  from jeepney.wrappers import unwrap_msg
  t = Properties(DBusAddress(path, OBEX, OBEX + ".Transfer1"))
  end = clock() + timeout
  while True:
    try:
      st = unwrap_msg(conn.send_and_get_reply(t.get("Status"), timeout=2))[0][1]
    except Exception:
      # obexd drops the object right after it completes
      return "complete"
    if st in ("complete", "error"):
      return st
    if clock() >= end:
      return "timeout"
    sleep(0.1)


def fetch_art(bz, player: str, handle: str, dest: str, log, conn_fn=_obex_conn, staging: str = ART_STAGING,
              sleep=time.sleep) -> str | None:
  # BlueZ 5.79+: ImgHandle is only valid while a BIP session is up on ObexPort.
  # obexd runs as root on the system bus (dpbridge-obex.service). 5.72 has no ObexPort: None.
  if not handle:
    return None
  try:
    port = bz.get(player, PLAYER_IF, "ObexPort")
  except Exception:
    return None
  if not port:
    return None
  try:
    from jeepney import DBusAddress, new_method_call
    from jeepney.wrappers import unwrap_msg
  except Exception as e:
    log(f"dpb nowplaying: no jeepney, {e!r}")
    return None
  conn, sess = None, None
  client = DBusAddress("/org/bluez/obex", OBEX, OBEX + ".Client1")
  try:
    conn = conn_fn()
    device = bz.get(player, PLAYER_IF, "Device")
    mac = str(device).rsplit("/dev_", 1)[-1].replace("_", ":")
    sess = unwrap_msg(conn.send_and_get_reply(
      new_method_call(client, "CreateSession", "sa{sv}", (mac, {"Target": ("s", "bip-avrcp"), "PSM": ("q", int(port))})),
      timeout=5,
    ))[0]
    # obexd writes as root; stage in our own dir, then copy so the UI file is ours
    os.makedirs(staging, exist_ok=True)
    os.chmod(staging, 0o777)
    tmp = os.path.join(staging, "art")
    if os.path.exists(tmp):
      os.unlink(tmp)
    img = DBusAddress(sess, OBEX, OBEX + ".Image1")
    xfer = unwrap_msg(conn.send_and_get_reply(new_method_call(img, "GetThumbnail", "ss", (tmp, handle)), timeout=8))[0]
    st = _wait_transfer(conn, xfer, 8.0, sleep=sleep)
    if st != "complete" or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
      log(f"dpb nowplaying: cover art transfer {st}")
      return None
    with open(tmp, "rb") as f:
      data = f.read()
    os.unlink(tmp)
    part = dest + ".tmp"
    with open(part, "wb") as f:
      f.write(data)
    os.replace(part, dest)
    return dest
  except Exception as e:
    log(f"dpb nowplaying: cover art skipped, {e!r}")
    return None
  finally:
    if conn is not None:
      if sess is not None:
        try:
          conn.send_and_get_reply(new_method_call(client, "RemoveSession", "o", (sess,)), timeout=2)
        except Exception:
          pass
      try:
        conn.close()
      except Exception:
        pass


def prune_art(keep: str | None, prefix: str = ART_PREFIX):
  d, base = os.path.split(prefix)
  try:
    names = os.listdir(d)
  except OSError:
    return
  for n in names:
    p = os.path.join(d, n)
    if n.startswith(base + "-") and n.endswith(".jpg") and p != keep:
      try:
        os.unlink(p)
      except OSError:
        pass


def publish(objects, get_pos, fetch, prev: dict, log, aplay_running=True, control_error=False) -> dict:
  path = find_player(objects)
  if path is None:
    state = dict(EMPTY)
  else:
    p = props(objects, path, PLAYER_IF)
    track = p.get("Track") or {}
    status = p.get("Status") or ""
    pos = p.get("Position")
    if get_pos is not None:
      try:
        pos = get_pos(path)
      except Exception:
        pass
    handle = (unwrap(track) or {}).get("ImgHandle") or ""
    title = str((unwrap(track) or {}).get("Title") or "").strip()
    art = None
    if handle:
      if prev.get("art") and prev.get("title") == title:
        art = prev.get("art")
      else:
        art = fetch(path, handle)
    tpath, tp = find_transport(objects, p.get("Device"))
    stream = stream_label(tp.get("Codec"), tp.get("Configuration")) if tpath else ""
    err = error_line(status, tp.get("State") if tpath else None, tpath is not None, aplay_running, control_error)
    state = track_state(track, status, pos, art, stream, err)
  if state != prev:
    write_state(state)
  return state


def run(bz, log, sleep=time.sleep, clock=time.monotonic, engaged_fn=lambda: False, aplay_fn=aplay_is_running):
  prev, last_cmd, last_t, control_error, control_until = {}, None, None, False, 0.0
  failed: dict[str, float] = {}
  write_state(EMPTY)
  try:
    while True:
      try:
        objects = bz.objects()
        now = clock()
        if control_error and now >= control_until:
          control_error = False
        cmd, last_cmd, last_t = accept_command(take_command(), engaged_fn(), now, last_cmd, last_t)
        if cmd:
          player = find_player(objects)
          try:
            if not player:
              raise RuntimeError("no player")
            bz.call(player, PLAYER_IF, METHODS[cmd])
            control_error = False
          except Exception as e:
            log(f"dpb nowplaying: {cmd} failed, {e!r}")
            control_error, control_until = True, now + 3.0
        def get_pos(path, _bz=bz):
          return _bz.get(path, PLAYER_IF, "Position")
        def art(path, handle, _bz=bz, _log=log):
          # a failed handle waits ART_RETRY_S instead of blocking every poll
          if clock() < failed.get(handle, 0.0):
            return None
          got = fetch_art(_bz, path, handle, art_path(handle), _log)
          if got is None:
            if len(failed) > 64:
              failed.clear()
            failed[handle] = clock() + ART_RETRY_S
          else:
            prune_art(got)
          return got
        prev = publish(objects, get_pos, art, prev, log, aplay_fn(), control_error)
      except Exception as e:
        log(f"dpb nowplaying: {e!r}, retrying")
        try:
          write_state(EMPTY)
          prev = dict(EMPTY)
        except Exception:
          pass
      sleep(POLL_S)
  finally:
    try:
      write_state(EMPTY)
    except Exception:
      pass


def main():
  from jeepney.io.blocking import open_dbus_connection
  from openpilot.common.swaglog import cloudlog
  from openpilot.system.dpbridge.bluez import Bluez

  sm = None
  try:
    import openpilot.cereal.messaging as messaging
    sm = messaging.SubMaster(["deviceState", "selfdriveState"])
  except Exception:
    pass

  def engaged():
    if sm is None:
      return False
    sm.update(0)
    try:
      return bool(sm["deviceState"].started and sm["selfdriveState"].enabled)
    except Exception:
      return False

  run(Bluez(open_dbus_connection(bus="SYSTEM")), cloudlog.warning, engaged_fn=engaged)


if __name__ == "__main__":
  main()
