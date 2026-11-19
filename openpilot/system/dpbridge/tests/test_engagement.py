import ast
from pathlib import Path

from openpilot.system.dpbridge import PROCESSES

ROOT = Path(__file__).resolve().parents[4]


def dpbridge_procs() -> set[str]:
  # every manager process that runs a dpbridge module
  tree = ast.parse((ROOT / 'openpilot/system/manager/process_config.py').read_text())
  return {c.args[0].value for c in ast.walk(tree) if isinstance(c, ast.Call) and len(c.args) >= 2
          and isinstance(c.args[1], ast.Constant) and str(c.args[1].value).startswith('openpilot.system.dpbridge.')}


def not_running_filter() -> ast.SetComp:
  # the set comprehension selfdrived turns into processNotRunning
  tree = ast.parse((ROOT / 'openpilot/selfdrive/selfdrived/selfdrived.py').read_text())
  for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'not_running' for t in node.targets):
      return node.value
  raise AssertionError('not_running not found in selfdrived')


def test_every_dpbridge_process_is_exempt():
  assert dpbridge_procs() == PROCESSES == {'btagentd', 'dpb_a2dp', 'dpb_nowplaying', 'dpb_kernel', 'dashkitd'}


def test_selfdrived_skips_dpbridge_processes():
  comp = not_running_filter()
  cond = ast.unparse(comp.generators[0].ifs[0])
  assert 'p.name not in' in cond and '*DPBRIDGE_PROCESSES' in cond
  # and the comprehension really filters with it: evaluate it on fake processes
  class P:
    def __init__(self, name):
      self.name, self.running, self.shouldBeRunning = name, False, True
  procs = [P(n) for n in (*PROCESSES, 'controlsd')]
  env = {'self': type('S', (), {'sm': {'managerState': type('M', (), {'processes': procs})}})(),
         'JetlinkEvents': type('J', (), {'OPTIONAL_PROCESSES': frozenset()}), 'DPBRIDGE_PROCESSES': PROCESSES}
  assert eval(compile(ast.Expression(comp), 'selfdrived', 'eval'), env) == {'controlsd'}


def test_dpbridge_processes_restart_after_a_crash():
  tree = ast.parse((ROOT / 'openpilot/system/manager/process_config.py').read_text())
  kinds = {c.args[0].value: c.func.id for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
           and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value in PROCESSES}
  assert kinds == dict.fromkeys(PROCESSES, 'RestartingPythonProcess')
