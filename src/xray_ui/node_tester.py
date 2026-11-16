from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .models import AppConfig, MixedInbound, Node
from .process import reserve_internal_ports
from .xray_config import build_xray_config

DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"


@dataclass(frozen=True, slots=True)
class TestResult:
    elapsed_ms: int
    status: int


def test_node(
    node: Node,
    xray_dir: Path,
    test_url: str = DEFAULT_TEST_URL,
    timeout: float = 10,
) -> TestResult:
    executable = xray_dir / "xray.exe"
    if not executable.exists():
        raise FileNotFoundError("尚未安装 Xray-core")
    public_port = _free_port()
    inbound = MixedInbound("test", public_port, node.id)
    app_config = AppConfig(nodes=[node], inbounds=[inbound])
    internal = reserve_internal_ports(1)[0]
    runtime = build_xray_config(app_config, {inbound.id: internal})
    # 节点测试无需 Mixed 前端，直接使用内部 HTTP 入站。
    http_inbound = next(item for item in runtime["inbounds"] if item["protocol"] == "http")
    http_port = int(http_inbound["port"])
    process: subprocess.Popen[str] | None = None
    with tempfile.TemporaryDirectory(prefix="xray-ui-test-") as temp_name:
        config_path = Path(temp_name) / "config.json"
        config_path.write_text(json.dumps(runtime, ensure_ascii=False), encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            [str(executable), "run", "-c", str(config_path)],
            cwd=xray_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        try:
            _wait_for_port(http_port, process, timeout=3)
            proxy = urllib.request.ProxyHandler(
                {"http": f"http://127.0.0.1:{http_port}", "https": f"http://127.0.0.1:{http_port}"}
            )
            opener = urllib.request.build_opener(proxy)
            started = time.perf_counter()
            with opener.open(test_url, timeout=timeout) as response:
                response.read(1)
                elapsed = round((time.perf_counter() - started) * 1000)
                return TestResult(elapsed, int(response.status))
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    capture_output=True,
                    check=False,
                )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Xray 在节点测试期间意外退出")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError("等待 Xray 测试端口超时")
