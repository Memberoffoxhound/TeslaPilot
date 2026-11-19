import os

import numpy as np
import pytest

from openpilot.selfdrive.ui.dpb_music import Music, DEFAULT_DB
from openpilot.selfdrive.ui.soundd import AudibleAlert, Soundd

N = 4096


@pytest.fixture
def fifo(tmp_path):
  p = tmp_path / 'a2dp.fifo'
  os.mkfifo(p)
  w = os.open(p, os.O_RDWR | os.O_NONBLOCK)
  yield p, w
  os.close(w)


def tone(n, v=8000):
  return (np.full(n, v, dtype=np.int16)).tobytes()


def music(tmp_path, fifo, db=None):
  vol = tmp_path / 'db'
  if db is not None:
    vol.write_text(str(db))
  return Music(fifo=str(fifo[0]), vol_file=str(vol))


def soundd(m=None):
  s = Soundd()
  if m is not None:
    s.music = m
  return s


@pytest.mark.parametrize('alert', ['sound', 'shutter'])
def test_alert_output_bit_identical(tmp_path, fifo, alert):
  ref, mix = soundd(), soundd(music(tmp_path, fifo))
  for s in (ref, mix):
    if alert == 'sound':
      s.current_volume = 0.7
      s.update_alert(AudibleAlert.warningImmediate)
    else:
      s.shutter_idx = 0
  for _ in range(5 if alert == 'sound' else -(-len(ref.shutter) // N)):
    os.write(fifo[1], tone(N))
    out = ref.get_sound_data(N)
    assert out.any() and np.array_equal(out, mix.get_sound_data(N))
  assert mix.music.fd is not None


def test_no_fifo_is_stock(tmp_path):
  ref, mix = soundd(), soundd(Music(fifo=str(tmp_path / 'none'), vol_file=str(tmp_path / 'db')))
  for s in (ref, mix):
    s.update_alert(AudibleAlert.engage)
  for _ in range(3):
    assert np.array_equal(ref.get_sound_data(N), mix.get_sound_data(N))


def test_mix_level_ramp_and_mute(tmp_path, fifo):
  m, t = music(tmp_path, fifo), 100.
  g = 10 ** (DEFAULT_DB / 20)
  levels = []
  for _ in range(14):
    os.write(fifo[1], tone(N))
    levels.append(m.get(N, False, now=t)[0])
    t += N / 48000
  assert levels == sorted(levels) and levels[-1] == pytest.approx(g * 8000 / 32768)
  os.write(fifo[1], tone(N))
  assert m.get(N, True, now=t) is None  # muted in the same block
  t += 0.4
  os.write(fifo[1], tone(N))
  assert m.get(N, False, now=t) is None  # still waiting
  t += 0.2
  os.write(fifo[1], tone(N))
  assert 0 < m.get(N, False, now=t)[0] < g * 8000 / 32768 / 4  # fading back in


@pytest.mark.parametrize('db,gain', [(0, 1.), (6, 1.), ('x', 10 ** (DEFAULT_DB / 20)), (-100, 10 ** -3)])
def test_volume_follows_music_db(tmp_path, fifo, db, gain):
  m = music(tmp_path, fifo, db)
  m.fade = 1.
  os.write(fifo[1], tone(N, 16384))
  assert m.get(N, False, now=1.)[0] == pytest.approx(0.5 * gain)


def test_loud_music_is_clipped(tmp_path, fifo):
  m = music(tmp_path, fifo, 0)
  m.fade = 1.
  s = soundd(m)
  s.current_alert = AudibleAlert.none
  s.current_volume = 1.
  os.write(fifo[1], tone(N, 32767))
  out = s.get_sound_data(N)
  assert out.max() <= 1.0 + 1e-6 and out.min() >= -1.0 - 1e-6


def test_volume_read_once_per_second(tmp_path, fifo):
  m = music(tmp_path, fifo, -20)
  m.get(N, False, now=10.)
  (tmp_path / 'db').write_text('-30')
  m.get(N, False, now=10.5)
  assert m.db == -20
  m.get(N, False, now=11.)
  assert m.db == -30


def test_short_read_pads_and_backlog_drops_oldest(tmp_path, fifo):
  m = music(tmp_path, fifo)
  m.fade = 1.
  os.write(fifo[1], tone(100))
  x = m.get(N, False, now=1.)
  assert x[99] > 0 and not x[100:].any()
  for v in range(1, 7):
    os.write(fifo[1], tone(N, v * 1000))
  first = m.get(N, False, now=2.)
  assert first[0] == pytest.approx(5000 / 32768 * 10 ** (DEFAULT_DB / 20))


def test_open_retried_once_per_second(tmp_path):
  p = tmp_path / 'late.fifo'
  m = Music(fifo=str(p), vol_file=str(tmp_path / 'db'))
  assert m.get(N, False, now=1.) is None
  os.mkfifo(p)
  w = os.open(p, os.O_RDWR | os.O_NONBLOCK)
  try:
    assert m.get(N, False, now=1.5) is None and m.fd is None
    m.get(N, False, now=2.)
    assert m.fd is not None
  finally:
    os.close(w)


def test_errors_give_silence(tmp_path, fifo):
  m = music(tmp_path, fifo)
  m.get(N, False, now=1.)
  os.close(m.fd)
  m.fd = 999999
  assert m.get(N, False, now=2.) is None
  s = soundd(m)
  s.current_alert = AudibleAlert.none
  assert np.array_equal(s.get_sound_data(N), soundd().get_sound_data(N))
