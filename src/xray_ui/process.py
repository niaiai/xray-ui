from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .models import AppConfig
from .storage import application_dir
from .xray_config import build_xray_config


class XrayProcessManager:
    def __init__(self, on_log: Callable[[str], None] | None = None) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.on_log = on_log or (lambda _: None)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, config: AppConfig, xray_dir: Path) -> None:
        if self.running:
            raise RuntimeError("Xray 已在运行")
        runtime = build_xray_config(config)
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
        self.process = subprocess.Popen(
            [str(executable), "run", "-c", str(config_path)],
            cwd=xray_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        threading.Thread(target=self._read_logs, daemon=True).start()

    def stop(self) -> None:
        process = self.process
        self.process = None
        if not process or process.poll() is not None:
            return
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True,
            check=False,
        )

    def _read_logs(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        for line in process.stdout:
            self.on_log(line.rstrip())
