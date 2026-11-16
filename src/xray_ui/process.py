from __future__ import annotations

import json
import socket
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .mixed_proxy import MixedProxyGroup, MixedTarget
from .models import AppConfig
from .storage import default_data_dir
from .xray_config import InternalPorts, build_xray_config


def reserve_internal_ports(count: int) -> list[InternalPorts]:
    sockets: list[socket.socket] = []
    ports: list[int] = []
    try:
        for _ in range(count * 2):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
            ports.append(sock.getsockname()[1])
    finally:
        for sock in sockets:
            sock.close()
    return [InternalPorts(ports[index * 2], ports[index * 2 + 1]) for index in range(count)]


class XrayProcessManager:
    def __init__(self, on_log: Callable[[str], None] | None = None) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.mixed = MixedProxyGroup()
        self.on_log = on_log or (lambda _: None)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, config: AppConfig, xray_dir: Path) -> None:
        if self.running:
            raise RuntimeError("Xray 已在运行")
        assignments = dict(
            zip((item.id for item in config.inbounds), reserve_internal_ports(len(config.inbounds)))
        )
        runtime = build_xray_config(config, assignments)
        runtime_dir = default_data_dir() / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config_path = runtime_dir / "xray.json"
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
        targets = [
            MixedTarget(
                item.listen, item.port, assignments[item.id].socks, assignments[item.id].http
            )
            for item in config.inbounds
        ]
        try:
            self.mixed.start(targets)
        except Exception:
            self.stop()
            raise
        threading.Thread(target=self._read_logs, daemon=True).start()

    def stop(self) -> None:
        self.mixed.stop()
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
