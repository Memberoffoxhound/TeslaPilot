# Loads asound.conf with the box's libasound and plays through dpb_a2dp into a FIFO, as bluealsa-aplay does.
import ctypes
import ctypes.util
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
FIFO = '/run/dpbridge/a2dp.fifo'
lib = ctypes.util.find_library('asound')
pytestmark = pytest.mark.skipif(lib is None, reason='no libasound')


def config(text):
  a = ctypes.CDLL(lib)
  cfg = ctypes.c_void_p()
  assert a.snd_config_top(ctypes.byref(cfg)) == 0
  for t in (Path('/usr/share/alsa/alsa.conf').read_text(), text):
    b, inp = t.encode(), ctypes.c_void_p()
    assert a.snd_input_buffer_open(ctypes.byref(inp), b, len(b)) == 0
    r = a.snd_config_load(cfg, inp)
    a.snd_input_close(inp)
    assert r == 0
  return a, cfg


def test_only_defines_dpb_a2dp():
  text = (HERE / 'asound.conf').read_text()
  assert FIFO in text and '!default' not in text and 'dmix' not in text and 'hw:' not in text


def test_dpb_a2dp_writes_s16_mono_to_the_fifo(tmp_path):
  fifo = tmp_path / 'a2dp.fifo'
  os.mkfifo(fifo)
  rd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
  a, cfg = config((HERE / 'asound.conf').read_text().replace(FIFO, str(fifo)))
  pcm = ctypes.c_void_p()
  assert a.snd_pcm_open_lconf(ctypes.byref(pcm), b'dpb_a2dp', 0, 0, cfg) == 0
  try:
    # what bluealsa-aplay asks for: stereo S16 at 44.1 kHz, plug converts
    assert a.snd_pcm_set_params(pcm, 2, 3, 2, 44100, 1, 100000) == 0
    buf = (ctypes.c_int16 * 882)(*([8000] * 882))
    assert a.snd_pcm_writei(pcm, buf, 441) == 441
    a.snd_pcm_drain(pcm)
  finally:
    a.snd_pcm_close(pcm)
  data = os.read(rd, 1 << 16)
  os.close(rd)
  assert len(data) == 480 * 2  # 10 ms at 48 kHz, mono S16
  assert int.from_bytes(data[600:602], 'little', signed=True) == pytest.approx(8000, abs=100)
