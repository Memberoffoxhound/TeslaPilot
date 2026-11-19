# MADS lateral-only driver monitoring, always at least as strict as stock
from opendbc.car.structs import car
from openpilot.cereal import custom, log
from openpilot.common.realtime import DT_DMON
from openpilot.selfdrive.monitoring.policy import DriverMonitoring
from openpilot.selfdrive.monitoring.test_monitoring import msg_ATTENTIVE, msg_DISTRACTED


def make_sm(driver_state, lat_active=False, mads_enabled=False, enabled=False, v_ego=20.0, gas=False):
  cs = car.CarState.new_message(vEgo=v_ego, gasPressed=gas, gearShifter=car.CarState.GearShifter.drive)
  model = log.ModelDataV2.new_message()
  model.meta.disengagePredictions.brakeDisengageProbs = [0.0]
  sd_sp = custom.SelfdriveStateSP.new_message()
  sd_sp.mads.enabled = mads_enabled
  return {
    'driverStateV2': driver_state, 'carState': cs, 'carControl': car.CarControl.new_message(latActive=lat_active),
    'selfdriveState': log.SelfdriveState.new_message(enabled=enabled), 'selfdriveStateSP': sd_sp,
    'modelV2': model, 'extrinsicsCalibration': log.ExtrinsicsCalibration.new_message(rpyCalib=[0., 0., 0.]),
  }


def run(seconds, **kw):
  DM = DriverMonitoring()
  levels = []
  for i in range(int(seconds / DT_DMON)):
    sm = make_sm(kw.get('state', msg_DISTRACTED), **{k: (v(i) if callable(v) else v) for k, v in kw.items() if k != 'state'})
    DM.run_step(sm)
    levels.append(DM.alert_level)
  return levels, DM


RED = DriverMonitoring().settings._VISION_POLICY_ALERT_3_TIMEOUT + 2


def test_lat_only_distracted_reaches_red():
  levels, _ = run(RED, lat_active=True, mads_enabled=True)
  assert levels[-1] == 3


def test_stock_disengaged_has_no_alert():
  levels, _ = run(RED)
  assert max(levels) == 0


def test_lat_only_stops_do_not_reset_awareness():
  # latActive drops at every stop, MADS stays engaged: awareness keeps counting down
  levels, _ = run(RED, mads_enabled=True, lat_active=lambda i: (i // 20) % 2 == 0)
  assert levels[-1] == 3


def test_lat_only_gas_does_not_count_as_engaged():
  levels, _ = run(RED, lat_active=True, mads_enabled=True, gas=True)
  assert levels[-1] == 3


def test_lat_only_attentive_no_alert():
  levels, _ = run(RED, state=msg_ATTENTIVE, lat_active=True, mads_enabled=True)
  assert max(levels) == 0
