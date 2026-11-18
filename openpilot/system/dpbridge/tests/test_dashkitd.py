from openpilot.system.dpbridge.dkwire import pack

GOOD = pack([(1, 0, 0x257, bytes(8))])


class Clock:
  def __init__(self):
    self.t = 0.0

  def __call__(self):
    return self.t


class FakeLink:
  # replays (gap_s, payload) pairs; payload None means recv timed out
  def __init__(self, script, clock):
    self.script, self.clock, self.pings = list(script), clock, []

  def ping(self):
    self.pings.append(self.clock.t)

  def recv(self, timeout):
    if not self.script:
      self.clock.t += timeout
      return None
    gap, b = self.script.pop(0)
    self.clock.t += gap
    return b


def run(script):
  from openpilot.system.dpbridge.dashkitd import stream
  clock = Clock()
  link, out = FakeLink(script, clock), []
  stream(link, out.append, mono=clock)
  return link, out, clock


def test_publishes_only_valid_payloads():
  _, out, _ = run([(0.02, GOOD), (0.02, b'\x05junk'), (0.02, b''), (0.02, GOOD)])
  assert out == [GOOD, GOOD]


def test_pings_every_15s_while_streaming():
  link, _, _ = run([(0.5, GOOD)] * 80)  # 40 s of traffic
  assert link.pings[0] == 0
  gaps = [b - a for a, b in zip(link.pings, link.pings[1:], strict=False)]
  assert len(link.pings) >= 3 and all(15 <= g < 16 for g in gaps)


def test_returns_after_silence():
  _, out, clock = run([(0.1, GOOD)])
  assert out == [GOOD]
  assert 10 < clock.t < 12


def test_log_only():
  from pathlib import Path
  src = (Path(__file__).parents[1] / 'dashkitd.py').read_text()
  assert "PubMaster(['customReservedRawData0'])" in src
  assert not any(w in src for w in ('sendcan', 'panda', 'carControl', 'SubMaster'))


def run_probe(script, ver='0.3.2'):
  from openpilot.system.dpbridge.dashkitd import probe
  clock = Clock()
  link = FakeLink(script, clock)
  link.open = lambda: ver
  return probe(link, mono=clock)


def test_probe_passes_with_a_live_stream():
  assert run_probe([(0.1, GOOD)] * 20)


def test_probe_fails_on_garbage_silence_or_no_version():
  assert not run_probe([(0.1, b'\x05junk')] * 20)
  assert not run_probe([])
  assert not run_probe([(0.1, GOOD)] * 20, ver='')
