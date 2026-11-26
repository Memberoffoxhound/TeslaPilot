import math

from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.params_compat import get_bool, is_set, put_bool, remove
from openpilot.selfdrive.controls.lib.signal_turn import MAX_SPEED_MPS, SignalTurnEvidence

ATI_PARAM = "AutomaticTurnInitiation"
LEGACY_TURN_PARAMS = ("TurnDesires", "TurnDesiresModelConfirm", "TurnDesiresNav")
REFRESH_NS = 1_000_000_000
TURN_SPEED_FORCE = 20 * CV.MPH_TO_MS
LEFT_MODS = frozenset(("left", "sharpleft"))
RIGHT_MODS = frozenset(("right", "sharpright"))


def migrate_turn_initiation_params(params) -> None:
  if not is_set(params, ATI_PARAM) and get_bool(params, "TurnDesires", False):
    put_bool(params, ATI_PARAM, True, block=True)
  for key in LEGACY_TURN_PARAMS:
    remove(params, key)


def within_turn_window(speed, distance):
  return math.isfinite(speed) and speed >= 0 and math.isfinite(distance) and 0 <= distance <= min(90., max(35., speed * 6.))


def _modifier(text):
  return (text or "").replace(" ", "").replace("-", "").lower()


def _flag(container, name, default=True):
  if container is None:
    return default
  try:
    if hasattr(container, "get"):
      return bool(container.get(name, default))
    return bool(container[name])
  except (KeyError, TypeError, AttributeError, IndexError):
    return default


def _service_ok(sm, name):
  return _flag(getattr(sm, "valid", None), name, True) and _flag(getattr(sm, "alive", None), name, True)


def _plan(sm):
  if not _service_ok(sm, "longitudinalPlan") or not _flag(getattr(sm, "seen", None), "longitudinalPlan", True):
    return None
  try:
    return sm["longitudinalPlan"]
  except (KeyError, TypeError):
    return None


def _plan_should_stop(sm):
  plan = _plan(sm)
  if plan is None:
    return False
  try:
    return bool(plan.shouldStop)
  except (AttributeError, TypeError):
    return False


def _nav_instruction(sm):
  try:
    if not _service_ok(sm, "navInstruction"):
      return None
    inst = sm["navInstruction"]
    if inst is None or inst.maneuverType != "turn":
      return None
    return inst
  except (KeyError, AttributeError, TypeError):
    return None


def _car_ok(sm):
  if not (_service_ok(sm, "carState") and _service_ok(sm, "carControl")):
    return False
  try:
    cs = sm["carState"]
    return not getattr(cs, "steerFaultTemporary", False) and not getattr(cs, "steerFaultPermanent", False)
  except (KeyError, AttributeError, TypeError):
    return False


class TurnIntent:
  def __init__(self, params=None):
    self.params = params if params is not None else Params()
    migrate_turn_initiation_params(self.params)
    self.signal_model = SignalTurnEvidence()
    self.requested = get_bool(self.params, ATI_PARAM, False)
    self.applied = self.requested
    self.signal_stop_hold = False
    self.signal_stop_completed = False
    self._last_read_ns = None

  @property
  def enabled(self) -> bool:
    return self.applied

  def _sample_preference(self, now_ns: int, *, signaling: bool, maneuver_active: bool) -> bool:
    if type(now_ns) is not int or now_ns <= 0 or (self._last_read_ns is not None and now_ns < self._last_read_ns):
      self._last_read_ns = None
      self.requested = self.applied = False
      return False
    if self._last_read_ns is None or now_ns - self._last_read_ns >= REFRESH_NS:
      self.requested = get_bool(self.params, ATI_PARAM, False)
      self._last_read_ns = now_ns
    if not self.requested:
      self.applied = False
    elif not signaling and not maneuver_active:
      self.applied = True
    return self.applied

  def _update_stop_hold(self, cs, cc, model_stop, sm):
    one_blinker = cs.leftBlinker != cs.rightBlinker
    if not cc.latActive or not one_blinker:
      self.signal_stop_hold = self.signal_stop_completed = False
    elif cs.standstill:
      self.signal_stop_hold = False
      self.signal_stop_completed = True
    elif model_stop or _plan_should_stop(sm):
      self.signal_stop_hold = True
    elif self.signal_stop_completed:
      self.signal_stop_hold = self.signal_stop_completed = False

  def matching_nav_turn(self, sm) -> bool:
    try:
      cs = sm["carState"]
      inst = _nav_instruction(sm)
      if inst is None or not within_turn_window(cs.vEgo, inst.maneuverDistance):
        return False
      mod = _modifier(inst.maneuverModifier)
      return bool((mod in LEFT_MODS and cs.leftBlinker and not cs.rightBlinker) or
                  (mod in RIGHT_MODS and cs.rightBlinker and not cs.leftBlinker))
    except (KeyError, AttributeError, TypeError, ValueError):
      return False

  def select(self, sm, now_ns, current_desire, *, model_stop=False, waiting_for_lane=False):
    try:
      cs, cc = sm["carState"], sm["carControl"]
      signaling = bool(cs.leftBlinker or cs.rightBlinker)
    except (KeyError, TypeError, AttributeError):
      return current_desire
    if not self._sample_preference(now_ns, signaling=signaling, maneuver_active=current_desire != log.Desire.none):
      self.signal_stop_hold = self.signal_stop_completed = False
      self.signal_model.reset()
      return current_desire
    if _service_ok(sm, "carState") and _service_ok(sm, "carControl"):
      self._update_stop_hold(cs, cc, model_stop, sm)
    if current_desire != log.Desire.none:
      return current_desire
    if not _car_ok(sm) or not cc.latActive or not math.isfinite(cs.vEgo):
      return current_desire
    if self.signal_stop_hold or cs.standstill or cs.vEgo <= 0.1 or cs.leftBlinker == cs.rightBlinker:
      return current_desire
    if waiting_for_lane and self.matching_nav_turn(sm):
      return current_desire
    selected = self.nav_desire(sm, current_desire)
    if selected != log.Desire.none:
      return selected
    return self.signal_desire(sm, now_ns, current_desire)

  def nav_desire(self, sm, current_desire):
    try:
      cs, cc = sm["carState"], sm["carControl"]
      inst = _nav_instruction(sm)
      if (inst is None or not cc.latActive or cs.standstill or not math.isfinite(cs.vEgo) or
          not 0.1 < cs.vEgo < MAX_SPEED_MPS or not within_turn_window(cs.vEgo, inst.maneuverDistance)):
        return current_desire
      mod = _modifier(inst.maneuverModifier)
      if mod in LEFT_MODS and cs.leftBlinker and not cs.rightBlinker and not cs.leftBlindspot:
        return log.Desire.turnLeft
      if mod in RIGHT_MODS and cs.rightBlinker and not cs.leftBlinker and not cs.rightBlindspot:
        return log.Desire.turnRight
    except (KeyError, AttributeError, TypeError, ValueError):
      pass
    return current_desire

  def signal_desire(self, sm, now_ns, current_desire):
    try:
      cs, cc = sm["carState"], sm["carControl"]
      if cs.vEgo >= TURN_SPEED_FORCE:
        if cs.steeringPressed or not self.signal_model.current(cs, cc, _plan(sm), now_ns=now_ns):
          return current_desire
      if cs.leftBlinker and not cs.leftBlindspot:
        return log.Desire.turnLeft
      if cs.rightBlinker and not cs.rightBlindspot:
        return log.Desire.turnRight
    except (KeyError, AttributeError, TypeError, ValueError):
      pass
    return current_desire

  def observe(self, sm, model, *, model_ns, now_ns, lane_change_state=None):
    if not self.enabled or not _car_ok(sm):
      self.signal_model.reset()
      return False
    return self.signal_model.observe(sm["carState"], sm["carControl"], model, model_ns=model_ns,
                                     now_ns=now_ns, plan=_plan(sm), lane_change_state=lane_change_state)
