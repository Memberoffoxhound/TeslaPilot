import ast
import importlib.util
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]


def test_every_import_resolves():
  # lazy imports inside main() only fail on the device otherwise
  for path in PKG.glob('*.py'):
    for node in ast.walk(ast.parse(path.read_text())):
      names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
              [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
      for name in names:
        assert importlib.util.find_spec(name.split('.')[0]) is not None, f'{path.name}: {name}'
        if name.startswith('openpilot.'):
          assert importlib.util.find_spec(name) is not None, f'{path.name}: {name}'
