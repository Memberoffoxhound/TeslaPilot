# The one-line hook in launch_chffrplus.sh that runs boot.py before manager.
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def test_hook_in_launch_before_manager():
  text = (ROOT / 'launch_chffrplus.sh').read_text()
  hook = '[ -x "$DIR/tools/dpbridge/boot.py" ] && "$DIR/tools/dpbridge/boot.py" || true'
  assert text.count(hook) == 1
  agnos = text[text.index('if [ -f /AGNOS ]; then'):]
  agnos = agnos[:agnos.index('\n  fi\n')]
  assert hook in agnos and agnos.index('agnos_init') < agnos.index(hook)
  assert text.index(hook) < text.index('manager.py')
  assert (HERE / 'boot.py').stat().st_mode & 0o111
  # the hook never fails the launch, and nothing here draws an icon
  assert 'icon' not in (HERE / 'boot.py').read_text().lower()
  r = subprocess.run(['bash', '-c', 'set -e; DIR=/nonexistent; ' + hook + '; echo up'], capture_output=True, text=True)
  assert r.stdout.strip() == 'up'
