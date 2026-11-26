#!/usr/bin/env python3

import os
import unittest

from openpilot.common.test import OpenpilotTestCase
from openpilot.common.params import Params
import openpilot.system.manager.manager as manager
from openpilot.system.manager.process_config import managed_processes, procs
from openpilot.common.hardware import HARDWARE

os.environ['FAKEUPLOAD'] = "1"


class TestManager(OpenpilotTestCase):
  def setup_method(self):
    HARDWARE.set_power_save(False)

    # ensure clean CarParams
    params = Params()
    params.clear_all()

  def teardown_method(self):
    manager.manager_cleanup()

  def test_duplicate_procs(self):
    assert len(procs) == len(managed_processes), "Duplicate process names"

  def test_set_params_with_default_value(self):
    params = Params()
    params.clear_all()

    os.environ['PREPAREONLY'] = '1'
    manager.main()
    for k in params.all_keys():
      default_value = params.get_default_value(k)
      if default_value is not None:
        assert params.get(k) == default_value
    assert params.get("OpenpilotEnabledToggle")
    assert params.get("RouteCount") == 0

  def test_manager_init_migrates_legacy_turn_desires(self):
    from openpilot.common.params_compat import get_bool, is_set, put_bool
    from openpilot.selfdrive.controls.lib.turn_intent import ATI_PARAM, LEGACY_TURN_PARAMS

    params = Params()
    params.clear_all()
    put_bool(params, "TurnDesires", True, block=True)

    manager.manager_init()

    assert get_bool(params, ATI_PARAM, False) is True
    for key in LEGACY_TURN_PARAMS:
      assert not is_set(params, key)


if __name__ == "__main__":
  unittest.main()
