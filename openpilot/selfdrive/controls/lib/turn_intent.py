import math

from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.params_compat import get_bool
from openpilot.selfdrive.controls.lib.signal_turn import MAX_SPEED_MPS, SignalTurnEvidence

TURN_SPEED_FORCE = 20 * CV.MPH_TO_MS
LEFT_MODS = frozenset(("left", "sharpleft"))
RIGHT_MODS = frozenset(("right", "sharpright"))


def _modifier(text):
  return (text or "").replace(" ", "").replace("-", "").lower()


def _plan(sm):
  try:
    return sm["longitudinalPlan"]
  except (KeyError, TypeError):
    return None


def _plan_should_stop(sm):
  plan = _plan(sm)
  if plan is None:
    return False
  try:
    if hasattr(sm, "valid") and not sm.valid.get("longitudinalPlan", True):
      return False
    if hasattr(sm, "alive") and not sm.alive.get("longitudinalPlan", True):
      return False
    return bool(plan.shouldStop)
  except (AttributeError, TypeError):
    return False


def _nav_instruction(sm):
  try:
    if hasattr(sm, "valid") and not sm.valid.get("navInstruction", True):
      return None
    if hasattr(sm, "alive") and not sm.alive.get("navInstruction", True):
      return None
    inst = sm["navInstruction"]
    if inst is None or inst.maneuverType != "turn":
      return None
    return inst
  except (KeyError, AttributeError, TypeError):
    return None


class TurnIntent:
  def __init__(self, params=None):
    self.params = params if params is not None else Params()
    self.signal_model = SignalTurnEvidence()
    self.force = False
    self.model_confirm = False
    self.nav_turns = False
    self.signal_stop_hold = False
    self.signal_stop_completed = False
    self._param_read_counter = 0
    self._read_params()

  def _read_params(self):
    self.force = get_bool(self.params, "TurnDesires", False)
    self.model_confirm = get_bool(self.params, "TurnDesiresModelConfirm", False)
    self.nav_turns = get_bool(self.params, "TurnDesiresNav", False)

  def _update_params(self):
    if self._param_read_counter % 50 == 0:
      self._read_params()
    self._param_read_counter += 1

  def select(self, sm, now_ns, current_desire, *, model_stop=False):
    self._update_params()
    if not self.force:
      self.signal_stop_hold = self.signal_stop_completed = False
      self.signal_model.reset()
      return current_desire
    if current_desire != log.Desire.none:
      return current_desire
    if self.nav_turns:
      selected = self.nav_desire(sm, current_desire, model_stop=model_stop)
      if selected != log.Desire.none:
        return selected
    return self.signal_desire(sm, now_ns, current_desire, model_stop=model_stop)

  def nav_desire(self, sm, current_desire, *, model_stop=False):
    try:
      cs, cc = sm["carState"], sm["carControl"]
      inst = _nav_instruction(sm)
      if (inst is None or not cc.latActive or cs.standstill or not math.isfinite(cs.vEgo) or
          not 0 <= cs.vEgo < MAX_SPEED_MPS):
        return current_desire
      distance = inst.maneuverDistance
      if not math.isfinite(distance) or not 0 <= distance <= min(90., max(35., cs.vEgo * 6.)):
        return current_desire
      if model_stop or _plan_should_stop(sm):
        return current_desire
      mod = _modifier(inst.maneuverModifier)
      if mod in LEFT_MODS and cs.leftBlinker and not cs.rightBlinker and not cs.leftBlindspot:
        return log.Desire.turnLeft
      if mod in RIGHT_MODS and cs.rightBlinker and not cs.leftBlinker and not cs.rightBlindspot:
        return log.Desire.turnRight
    except (KeyError, AttributeError, TypeError, ValueError):
      pass
    return current_desire

  def signal_desire(self, sm, now_ns, current_desire, *, model_stop=False):
    try:
      cs, cc = sm["carState"], sm["carControl"]
      signaling = bool(cs.leftBlinker or cs.rightBlinker)
      if current_desire != log.Desire.none or not cc.latActive or not math.isfinite(cs.vEgo):
        return current_desire
      if cs.vEgo >= TURN_SPEED_FORCE:
        if (not self.model_confirm or cs.steeringPressed or
            not self.signal_model.current(cs, cc, _plan(sm), now_ns=now_ns)):
          return current_desire
      if not signaling:
        self.signal_stop_hold = self.signal_stop_completed = False
      elif cs.standstill:
        self.signal_stop_hold = False
        self.signal_stop_completed = True
      elif model_stop or _plan_should_stop(sm):
        self.signal_stop_hold = True
      elif self.signal_stop_completed:
        self.signal_stop_hold = self.signal_stop_completed = False
      if self.signal_stop_hold or cs.standstill or cs.vEgo <= 0.1 or cs.leftBlinker == cs.rightBlinker:
        return current_desire
      if cs.leftBlinker and not cs.leftBlindspot:
        return log.Desire.turnLeft
      if cs.rightBlinker and not cs.rightBlindspot:
        return log.Desire.turnRight
    except (KeyError, AttributeError, TypeError, ValueError):
      pass
    return current_desire
