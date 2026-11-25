import math

from openpilot.cereal import log

MAX_AGE_NS = 150_000_000
CONFIRM_NS = 100_000_000
MAX_SPEED_MPS = 14.


class SignalTurnEvidence:
  def __init__(self):
    self.reset()

  def reset(self):
    self.key = None
    self.since_ns = self.model_ns = 0
    self.ready = False

  @staticmethod
  def context(cs, cc, plan=None):
    try:
      direction = -1 if cs.leftBlinker and not cs.rightBlinker else 1 if cs.rightBlinker and not cs.leftBlinker else 0
      v_ego = cs.vEgo
      a_ego = getattr(cs, "aEgo", 0.0)
      if (not cc.latActive or cs.standstill or getattr(cs, "steerFaultTemporary", False) or
          getattr(cs, "steerFaultPermanent", False) or not direction or
          (cs.leftBlindspot and direction == -1) or (cs.rightBlindspot and direction == 1) or
          not math.isfinite(v_ego) or not 0.1 < v_ego < MAX_SPEED_MPS or
          not math.isfinite(a_ego) or a_ego > -0.5 or (plan is not None and plan.shouldStop)):
        return None
      return direction
    except (AttributeError, TypeError, ValueError):
      return None

  def current(self, cs, cc, plan=None, now_ns=None):
    key = self.context(cs, cc, plan)
    if not (self.ready and key is not None and key == self.key):
      return False
    if now_ns is not None and not (0 < self.model_ns <= now_ns <= self.model_ns + MAX_AGE_NS):
      return False
    return True

  def observe(self, cs, cc, model, *, model_ns, now_ns, plan=None, lane_change_state=None):
    key = self.context(cs, cc, plan)
    try:
      if (key is None or not 0 < model_ns <= now_ns <= model_ns + MAX_AGE_NS or
          getattr(model.action, "shouldStop", False)):
        self.reset()
        return False
      prediction = tuple(model.meta.desirePrediction)
      if len(prediction) != 32 or not all(math.isfinite(x) and 0 <= x <= 1 for x in prediction):
        self.reset()
        return False
      direction = int(log.Desire.turnLeft if key == -1 else log.Desire.turnRight)
      opposite = int(log.Desire.turnRight if key == -1 else log.Desire.turnLeft)
      for offset in range(0, 32, 8):
        if abs(sum(prediction[offset:offset + 8]) - 1.) > .01:
          self.reset()
          return False
      # Forecasts, rather than desireState, avoid reusing an injected desire as evidence.
      if any(prediction[offset + direction] < .6 or prediction[offset + opposite] > .2 or
             prediction[offset + int(log.Desire.laneChangeLeft)] + prediction[offset + int(log.Desire.laneChangeRight)] > .2
             for offset in (0, 8, 16)):
        self.reset()
        return False
      state = model.meta.laneChangeState if lane_change_state is None else lane_change_state
      ongoing = state in (log.LaneChangeState.laneChangeStarting, log.LaneChangeState.laneChangeFinishing)
      if ongoing and not self.ready:
        self.reset()
        return False
      if key != self.key or model_ns < self.model_ns or model_ns > self.model_ns + MAX_AGE_NS:
        self.reset()
        self.key, self.since_ns = key, model_ns
      if model_ns > self.model_ns:
        self.model_ns = model_ns
        self.ready = model_ns - self.since_ns >= CONFIRM_NS
      return self.current(cs, cc, plan, now_ns=now_ns)
    except (AttributeError, TypeError, ValueError, OverflowError):
      self.reset()
      return False
