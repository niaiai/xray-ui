import os

from xray_ui.process import _process_executable


def test_current_windows_process_can_be_identified():
    executable = _process_executable(os.getpid())
    assert executable is not None
    assert executable.exists()
    assert executable.name.lower() == "python.exe"


def test_missing_windows_process_is_not_identified():
    assert _process_executable(0x7FFFFFFF) is None
