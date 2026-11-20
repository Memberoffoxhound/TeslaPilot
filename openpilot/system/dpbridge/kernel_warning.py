# kernel_warning.txt as cards: (title, text, icon). Plain Python, the page and tests share it.
import os

from openpilot.common.basedir import BASEDIR

WARNING = os.path.join(BASEDIR, "tools/dpbridge/kernel_warning.txt")


def cards(path: str = WARNING) -> list[tuple[str, str, str]]:
  out = []
  with open(path) as f:
    blocks = f.read().split("\n\n")
  for block in blocks:
    title, icon, text = "", "", []
    for ln in block.splitlines():
      if ln.startswith("#") or not ln.strip():
        continue
      if ln.startswith("title:"):
        title = ln[6:].strip().replace("\\n", "\n")
      elif ln.startswith("icon:"):
        icon = ln[5:].strip()
      else:
        text.append(ln.strip())
    if title or text:
      out.append((title, " ".join(text), icon))
  return out
