from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Callable
from ctypes import byref, create_unicode_buffer, windll
from ctypes.wintypes import DWORD
from pathlib import Path

from .models import AppConfig
from .storage import application_dir
from .xray_config import build_xray_config


class XrayProcessManager:
    def __init__(self, on_log: Callable[[str], None] | None = None) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.pid: int | None = None
        self.executable: Path | None = None
        self.on_log = on_log or (lambda _: None)
        self.pid_path = application_dir() / "xray.pid"
        self.log_path = application_dir() / "log" / "xray-core.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def running(self) -> bool:
        if self.pid is None:
            return False
        actual = _process_executable(self.pid)
        if actual is not None and (
            self.executable is None
            or os.path.normcase(str(actual)) == os.path.normcase(str(self.executable))
        ):
            return True
        self._clear_process()
        return False

    def attach(self, xray_dir: Path) -> bool:
        if not self.pid_path.exists():
            return False
        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            self.pid_path.unlink(missing_ok=True)
            return False
        expected = (xray_dir / "xray.exe").resolve()
        actual = _process_executable(pid)
        if actual is None or os.path.normcase(str(actual)) != os.path.normcase(str(expected)):
            self.pid_path.unlink(missing_ok=True)
            return False
        self.pid = pid
        self.executable = expected
        self._start_log_reader(pid, self.log_path.stat().st_size if self.log_path.exists() else 0)
        return True

    def start(self, config: AppConfig, xray_dir: Path) -> None:
        if self.running:
            raise RuntimeError("Xray 已在运行")
        runtime = build_xray_config(config)
        xray_log_file = config.settings.xray_log_file.strip()
        if config.settings.enable_xray_log and xray_log_file:
            xray_log_path = Path(xray_log_file)
            if not xray_log_path.is_absolute():
                xray_log_path = xray_dir / xray_log_path
            xray_log_path.parent.mkdir(parents=True, exist_ok=True)
        config_path = application_dir() / "xray-runtime.json"
        config_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
        executable = xray_dir / "xray.exe"
        if not executable.exists():
            raise FileNotFoundError("尚未安装 Xray-core")
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        test = subprocess.run(
            [str(executable), "run", "-test", "-c", str(config_path)],
            cwd=xray_dir,
            text=True,
            capture_output=True,
            creationflags=creationflags,
            timeout=15,
            check=False,
        )
        if test.returncode:
            raise RuntimeError((test.stderr or test.stdout).strip() or "Xray 配置校验失败")
        log_offset = self.log_path.stat().st_size if self.log_path.exists() else 0
        with self.log_path.open("a", encoding="utf-8", newline="") as output:
            self.process = subprocess.Popen(
                [str(executable), "run", "-c", str(config_path)],
                cwd=xray_dir,
                text=True,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=creationflags | subprocess.DETACHED_PROCESS,
            )
        self.pid = self.process.pid
        self.executable = executable.resolve()
        self.pid_path.write_text(str(self.pid), encoding="utf-8")
        self._start_log_reader(self.pid, log_offset)

    def stop(self) -> None:
        pid = self.pid
        if pid is None:
            return
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True,
            check=False,
        )
        self._clear_process()

    def _clear_process(self) -> None:
        self.process = None
        self.pid = None
        self.executable = None
        self.pid_path.unlink(missing_ok=True)

    def _start_log_reader(self, pid: int, offset: int) -> None:
        threading.Thread(target=self._read_logs, args=(pid, offset), daemon=True).start()

    def _read_logs(self, pid: int, offset: int) -> None:
        self.log_path.touch(exist_ok=True)
        with self.log_path.open("r", encoding="utf-8", errors="replace") as log:
            log.seek(offset)
            while self.pid == pid and _process_executable(pid) is not None:
                line = log.readline()
                if line:
                    self.on_log(line.rstrip())
                else:
                    time.sleep(0.2)


def _process_executable(pid: int) -> Path | None:
    process = windll.kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return None
    try:
        size = DWORD(32768)
        buffer = create_unicode_buffer(size.value)
        if not windll.kernel32.QueryFullProcessImageNameW(process, 0, buffer, byref(size)):
            return None
        return Path(buffer.value).resolve()
    finally:
        windll.kernel32.CloseHandle(process)
