import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
KEYS = (ROOT / "openpilot/common/params_keys.h").read_text()
# every dpbridge file that reads or writes a param
FILES = [*(ROOT / "openpilot/system/dpbridge").glob("*.py"), *(ROOT / "tools/dpbridge").glob("*.sh"),
         ROOT / "openpilot/selfdrive/ui/dpb_music.py", ROOT / "openpilot/selfdrive/ui/mici/layouts/settings/bluetooth.py"]
PY = re.compile(r"""params\.(?:get|get_bool|put|put_bool|put_nonblocking|remove)\(\s*["']([A-Z]\w+)["']""")
SH = re.compile(r"params/d/(\w+)")


def test_every_dpbridge_param_exists():
  used = {k: f.name for f in FILES for k in PY.findall(f.read_text()) + SH.findall(f.read_text())}
  assert {"DpbBluetooth", "DashKitAddr", "DpbCmd", "DpbStatus", "DpbMusicOnroad"} <= set(used)
  missing = {k: f for k, f in used.items() if f'{{"{k}",' not in KEYS}
  assert not missing, missing


def test_music_onroad_on_by_default():
  # new name so a comma that stored the old "0" default picks up on
  assert '{"DpbMusicOnroad", {PERSISTENT, BOOL, "1"}}' in KEYS and "DpbA2dpOnroad" not in KEYS
