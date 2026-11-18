# Loads asound.conf with the box's libasound. Card-specific PCMs are swapped for null so no sound card is needed.
import ctypes
import ctypes.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
PLAYBACK, CAPTURE = 0, 1
lib = ctypes.util.find_library('asound')
pytestmark = pytest.mark.skipif(lib is None, reason='no libasound')


def config(*extra):
  a = ctypes.CDLL(lib)
  cfg = ctypes.c_void_p()
  assert a.snd_config_top(ctypes.byref(cfg)) == 0
  for text in (Path('/usr/share/alsa/alsa.conf').read_text(), (HERE / 'asound.conf').read_text(), *extra):
    b, inp = text.encode(), ctypes.c_void_p()
    assert a.snd_input_buffer_open(ctypes.byref(inp), b, len(b)) == 0
    r = a.snd_config_load(cfg, inp)
    a.snd_input_close(inp)
    assert r == 0
  return a, cfg


def opens(name, stream, *extra):
  a, cfg = config(*extra)
  pcm = ctypes.c_void_p()
  r = a.snd_pcm_open_lconf(ctypes.byref(pcm), name.encode(), stream, 0, cfg)
  if r == 0:
    a.snd_pcm_close(pcm)
  return r == 0


def test_default_capture_stays_on_sysdefault():
  # micd records from default; dmix (here on a missing card) can't capture
  assert opens('default', CAPTURE, 'pcm.!sysdefault { type null }')


def test_default_playback_goes_through_dmix():
  assert opens('default', PLAYBACK, 'pcm.!dpb_mix { type null }')
  assert not opens('default', PLAYBACK, 'pcm.!sysdefault { type null }')  # not around it


def test_dmix_buffer():
  a, cfg = config()
  node, val = ctypes.c_void_p(), ctypes.c_long()
  assert a.snd_config_search(cfg, b'pcm.dpb_mix.slave.buffer_size', ctypes.byref(node)) == 0
  assert a.snd_config_get_integer(node, ctypes.byref(val)) == 0
  assert val.value == 8192  # 8 periods of 1024, about 170 ms
