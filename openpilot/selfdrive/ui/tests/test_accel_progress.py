from openpilot.selfdrive.ui import accel_progress as ap


def test_provisioning():
  assert ap.provisioning('chestnut', 0.3, None) == ('download', 0.3)
  assert ap.provisioning('chestnut', 1.4, None) == ('download', 1.0)
  assert ap.provisioning('chestnut', None, {'stage': 'download', 'frac': 0.5}) is None
  assert ap.provisioning('jetlink', None, {'stage': 'download', 'frac': 0.5}) == ('download', 0.5)
  assert ap.provisioning('jetlink', None, {'stage': 'build', 'frac': 0.5}) == ('compile', None)
  assert ap.provisioning('jetlink', None, {'stage': 'ready'}) is None
  assert ap.provisioning('none', 0.1, {'stage': 'download'}) is None


def test_pulse_stays_visible():
  assert all(0.35 <= ap.pulse(t / 10) <= 1.0 for t in range(100))


def test_chestnut_download_reads_the_model_manager():
  from openpilot.cereal import custom
  ds = custom.ModelManagerSP.DownloadStatus
  mm = custom.ModelManagerSP.new_message()
  assert ap.chestnut_download(mm) is None
  bundle = mm.init('selectedBundle')
  bundle.status = ds.downloading
  bundle.init('models', 2)
  bundle.models[0].artifact.downloadProgress.progress = 100
  bundle.models[1].artifact.downloadProgress.progress = 20
  assert abs(ap.chestnut_download(mm) - 0.6) < 1e-6
  bundle.status = ds.downloaded
  assert ap.chestnut_download(mm) is None
  assert ap.chestnut_download(None) is None
