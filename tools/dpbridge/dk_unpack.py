#!/usr/bin/env python3
# DashKit frames from a route or rlog as CSV: log_mono_ns,dk_us,bus,addr,hex
# --check: print nothing, exit 0 only if both buses show up (bus 0 0x257, bus 1 0x249)
import argparse
import sys

from openpilot.system.dpbridge.dkwire import frames

EXPECT = {(0, 0x257), (1, 0x249)}


def unpack(msgs):
  for m in msgs:
    if m.which() == 'customReservedRawData0':
      for ts, bus, addr, data in frames(m.customReservedRawData0) or []:
        yield m.logMonoTime, ts, bus, addr, data


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument('route')
  ap.add_argument('--check', action='store_true')
  args = ap.parse_args()

  from openpilot.tools.lib.logreader import LogReader
  seen = set()
  for t, ts, bus, addr, data in unpack(LogReader(args.route)):
    seen.add((bus, addr))
    if not args.check:
      print(f'{t},{ts},{bus},{addr:#x},{data.hex()}')
  if args.check:
    missing = EXPECT - seen
    print(f"missing: {sorted(missing)}" if missing else "ok", file=sys.stderr)
    sys.exit(1 if missing else 0)


if __name__ == '__main__':
  main()
