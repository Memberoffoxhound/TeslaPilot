# text rules for the AR HUD card, kept free of raylib so they can be tested
ARRIVE_TYPE = 'arrive'
NOW_M = 15.0  # m, closer than this the card says Now (Here on arrival)


def card_word(distance: float, maneuver_type: str) -> str | None:
  # None means show the distance number
  if distance >= NOW_M:
    return None
  return 'Here' if maneuver_type == ARRIVE_TYPE else 'Now'


def eta_values(seconds: float, distance_text: str, arrive: str | None) -> list[tuple[str, str]]:
  # arrive is the clock text, or None when the clock is not valid
  values = [('time left', f'{max(1, round(max(0, seconds) / 60))} min'), ('distance', distance_text)]
  return [('arrive', arrive), *values] if arrive is not None else values


def eta_pick(values: list[tuple[str, str]], maneuver_type: str, t: float, rotate_s: float) -> tuple[str, str]:
  # arriving locks the first value (the arrive time when there is one)
  return values[0] if maneuver_type == ARRIVE_TYPE else values[int(t / rotate_s) % len(values)]
