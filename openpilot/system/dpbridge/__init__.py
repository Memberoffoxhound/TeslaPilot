# optional Bluetooth daemons: selfdrived never waits for them, so they can't block or drop engagement
PROCESSES = frozenset({'btagentd', 'dpb_a2dp', 'dpb_nowplaying', 'dashkitd'})
