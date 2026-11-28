from openpilot.selfdrive.navigation import hud_text as h


def test_arrival_card_says_here_a_turn_says_now():
  assert h.card_word(8.0, 'arrive') == 'Here'
  assert h.card_word(-20.0, 'arrive') == 'Here'
  assert h.card_word(8.0, 'turn') == 'Now'
  assert h.card_word(400.0, 'arrive') is None


def test_arrival_locks_the_arrive_time():
  values = h.eta_values(600, '2.1 mi', '9:41')
  assert values[0] == ('arrive', '9:41')
  assert all(h.eta_pick(values, 'arrive', t, 4.0) == ('arrive', '9:41') for t in (0, 4, 8, 12))
  seen = {h.eta_pick(values, 'turn', t, 4.0)[0] for t in (0, 4, 8)}
  assert seen == {'arrive', 'time left', 'distance'}


def test_no_arrive_time_without_a_valid_clock():
  values = h.eta_values(600, '2.1 mi', None)
  assert [v[0] for v in values] == ['time left', 'distance']
  assert h.eta_pick(values, 'arrive', 0, 4.0)[0] == 'time left'
  assert {h.eta_pick(values, 'turn', t, 4.0)[0] for t in (0, 4)} == {'time left', 'distance'}
