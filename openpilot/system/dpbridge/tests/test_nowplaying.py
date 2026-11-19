import json
from pathlib import Path

from openpilot.system.dpbridge.nowplaying import (
  EMPTY, PLAYER_IF, accept_command, aac_bitrate_kbps, error_line, find_player,
  fmt_mmss, parse_command, publish, sbc_bitrate_kbps, send_command, stream_label,
  take_command, track_state, unwrap, visible, write_state, read_state,
)


def test_fmt_mmss():
  assert fmt_mmss(0) == "0:00"
  assert fmt_mmss(999) == "0:00"
  assert fmt_mmss(1000) == "0:01"
  assert fmt_mmss(83000) == "1:23"
  assert fmt_mmss(244000) == "4:04"
  assert fmt_mmss(3600000) == "60:00"
  assert fmt_mmss(None) == "--:--"
  assert fmt_mmss("x") == "--:--"
  assert fmt_mmss(-1) == "--:--"
  assert fmt_mmss(0xFFFFFFFF) == "--:--"


def test_track_state_plain_and_variants():
  plain = track_state(
    {"Title": "Midnight City", "Artist": "M83", "Album": "Hurry Up, We're Dreaming", "Duration": 244000},
    "playing", 83000, art=None,
  )
  variant = track_state(
    {
      "Title": ("s", "Midnight City"),
      "Artist": ("s", "M83"),
      "Album": ("s", "Hurry Up, We're Dreaming"),
      "Duration": ("u", 244000),
    },
    "playing", ("u", 83000),
  )
  for st in (plain, variant):
    assert st["title"] == "Midnight City"
    assert st["artist"] == "M83"
    assert st["album"] == "Hurry Up, We're Dreaming"
    assert st["duration_ms"] == 244000
    assert st["position_ms"] == 83000
    assert st["status"] == "playing"
    assert st["art"] is None
    assert st["stream"] == "" and st["error"] == ""
  assert unwrap({"ImgHandle": ("s", "abc")})["ImgHandle"] == "abc"


def test_visible_and_empty():
  playing = track_state({"Title": "Song"}, "playing", 0)
  paused = track_state({"Title": "Song"}, "paused", 0)
  stopped = track_state({"Title": "Song"}, "stopped", 0)
  blank = track_state({}, "playing", 0)
  assert visible(playing) and visible(paused)
  assert not visible(stopped) and not visible(blank) and not visible(EMPTY) and not visible({})
  assert track_state({"Duration": 0xFFFFFFFF}, "playing", None)["duration_ms"] == 0
  assert visible(track_state({"Title": "Song"}, "error", 0, error="player error"))


def test_write_and_read_state(tmp_path):
  path = str(tmp_path / "nowplaying.json")
  st = track_state({"Title": "A", "Artist": "B"}, "playing", 1000)
  write_state(st, path)
  assert not Path(path + ".tmp").exists()
  assert read_state(path) == st
  assert json.loads(Path(path).read_text())["title"] == "A"
  assert read_state(str(tmp_path / "missing.json")) == {}


def _player(track, status="playing", device="/org/bluez/hci0/dev_AA_BB", **extra):
  p = {"Status": status, "Position": 0, "Device": device, "Track": track}
  p.update(extra)
  return {"/org/bluez/hci0/dev_AA_BB/player0": {PLAYER_IF: p}}


def _transport(codec=0, state="active", config=(0x21, 0x15, 53, 53), device="/org/bluez/hci0/dev_AA_BB"):
  return {"/org/bluez/hci0/dev_AA_BB/sep1/fd0": {
    "org.bluez.MediaTransport1": {"Device": device, "Codec": codec, "State": state, "Configuration": list(config)},
  }}


def test_publish_metadata_without_art(tmp_path, monkeypatch):
  from openpilot.system.dpbridge import nowplaying
  path = str(tmp_path / "nowplaying.json")
  monkeypatch.setattr(nowplaying, "STATE_PATH", path)
  objects = {
    "/org/bluez/hci0/dev_AA_BB/player0": {
      PLAYER_IF: {
        "Status": ("s", "playing"),
        "Position": ("u", 1000),
        "Device": ("o", "/org/bluez/hci0/dev_AA_BB"),
        "Track": ("a{sv}", {
          "Title": ("s", "Song"),
          "Artist": ("s", "Artist"),
          "Album": ("s", "Album"),
          "Duration": ("u", 60000),
        }),
      }
    },
    **_transport(),
  }
  fetched = []
  state = publish(objects, get_pos=lambda p: 1500, fetch=lambda p, h: fetched.append((p, h)) or None, prev={}, log=lambda m: None)
  assert find_player(objects).endswith("player0")
  assert state["title"] == "Song" and state["position_ms"] == 1500 and state["art"] is None
  assert state["stream"] == "SBC ~328 kbps" and state["error"] == ""
  assert fetched == []  # no ImgHandle on 5.72
  assert read_state(path)["artist"] == "Artist"
  empty = publish({}, get_pos=None, fetch=lambda p, h: "nope", prev=state, log=lambda m: None)
  assert empty == EMPTY and read_state(path) == EMPTY


def test_publish_fetches_art_once_per_title(tmp_path, monkeypatch):
  from openpilot.system.dpbridge import nowplaying
  monkeypatch.setattr(nowplaying, "STATE_PATH", str(tmp_path / "nowplaying.json"))
  objects = {**_player({"Title": "Song", "ImgHandle": "h1", "Duration": 1000}), **_transport()}
  calls = []
  s1 = publish(objects, None, lambda p, h: calls.append(h) or "/tmp/art.jpg", {}, lambda m: None)
  s2 = publish(objects, None, lambda p, h: calls.append(h) or "/tmp/art.jpg", s1, lambda m: None)
  assert s1["art"] == s2["art"] == "/tmp/art.jpg" and calls == ["h1"]
  assert s1["stream"] == "SBC ~328 kbps"


def test_parse_and_take_command(tmp_path):
  path = str(tmp_path / "nowplaying.cmd")
  assert parse_command("Play") == "play"
  assert parse_command("NEXT\n") == "next"
  assert parse_command("previous") == "previous"
  assert parse_command("pause") == "pause"
  assert parse_command("stop") is None and parse_command("") is None and parse_command("seek") is None
  assert send_command("Next", path)
  assert Path(path).read_text() == "next"
  assert take_command(path) == "next"
  assert not Path(path).exists()
  assert take_command(path) is None
  assert not send_command("stop", path)


def test_accept_command_debounce_and_engaged():
  a, last, t = accept_command("next", engaged=False, now=1.0, last_cmd=None, last_t=None)
  assert a == "next" and last == "next" and t == 1.0
  b, last2, t2 = accept_command("pause", engaged=False, now=1.1, last_cmd=last, last_t=t, debounce_s=0.4)
  assert b is None and last2 == "next" and t2 == 1.0
  c, last3, t3 = accept_command("pause", engaged=False, now=1.5, last_cmd=last2, last_t=t2, debounce_s=0.4)
  assert c == "pause" and last3 == "pause" and t3 == 1.5
  d, last4, t4 = accept_command("next", engaged=True, now=3.0, last_cmd=last3, last_t=t3)
  assert d is None and last4 == "pause" and t4 == 1.5
  assert accept_command(None, False, 4.0, last4, t4)[0] is None


def test_sbc_bitrate():
  # A2DP 12.9: 44.1 kHz, joint stereo, 16 blocks, 8 subbands, bitpool 53 is ~328 kbps
  cfg_441 = bytes([0x21, 0x15, 53, 53])
  assert sbc_bitrate_kbps(cfg_441) == 328
  # 48 kHz, same frame: 8*119*48000/(8*16)/1000 = 357
  cfg_48 = bytes([0x11, 0x15, 53, 53])
  assert sbc_bitrate_kbps(cfg_48) == 357
  # several capability bits: pick the highest freq (48 kHz) and joint
  assert sbc_bitrate_kbps(bytes([0x1F, 0xFF, 53, 53])) == 357
  assert sbc_bitrate_kbps(bytes([0x21, 0x15, 32, 53])) == 328  # max bitpool
  assert sbc_bitrate_kbps(b"\x00") is None
  assert stream_label(0, cfg_441) == "SBC ~328 kbps"
  assert stream_label(2, [0x80, 0x01, 0x00, 0x03, 0xE8, 0x00]) == "AAC ~256 kbps"
  assert stream_label(0xFF, b"") == "vendor"
  assert aac_bitrate_kbps([0x80, 0x01, 0x00, 0x03, 0xE8, 0x00]) == 256  # 0x03E800 = 256000
  assert aac_bitrate_kbps(b"") is None


def test_error_mapping(tmp_path, monkeypatch):
  assert error_line("playing", "active", True, True) == ""
  assert error_line("paused", "idle", True, True) == ""
  assert error_line("error", "active", True, True) == "player error"
  assert error_line("playing", None, False, True) == "no A2DP transport"
  assert error_line("playing", "idle", True, True) == "transport idle"
  assert error_line("playing", "pending", True, True) == "transport pending"
  assert error_line("playing", "active", True, False) == "aplay not running"
  assert error_line("playing", "active", True, False, control_error=True) == "control failed"
  assert error_line("paused", "active", True, True, control_error=True) == "control failed"
  st = track_state({"Title": "Song"}, "playing", 0, error="no A2DP transport")
  assert visible(st) and st["error"] == "no A2DP transport"
  assert visible(track_state({"Title": "Song"}, "error", 0, error="player error"))

  from openpilot.system.dpbridge import nowplaying
  monkeypatch.setattr(nowplaying, "STATE_PATH", str(tmp_path / "nowplaying.json"))
  objects = _player({"Title": "Song", "Duration": 1000})  # playing, no transport
  state = publish(objects, None, lambda p, h: None, {}, lambda m: None)
  assert state["error"] == "no A2DP transport" and state["stream"] == ""
  objects = {**_player({"Title": "Song", "Duration": 1000}), **_transport(state="idle")}
  assert publish(objects, None, lambda p, h: None, {}, lambda m: None, aplay_running=True)["error"] == "transport idle"
  objects = {**_player({"Title": "Song", "Duration": 1000}), **_transport()}
  assert publish(objects, None, lambda p, h: None, {}, lambda m: None, aplay_running=False)["error"] == "aplay not running"
  assert publish(objects, None, lambda p, h: None, {}, lambda m: None, control_error=True)["error"] == "control failed"
