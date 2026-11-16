from __future__ import annotations

import selectors
import socket
import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MixedTarget:
    listen: str
    port: int
    socks_port: int
    http_port: int


class MixedProxy:
    """在单个 TCP 端口上识别 SOCKS4/5 或 HTTP，并转发至 Xray 内部入站。"""

    def __init__(self, target: MixedTarget) -> None:
        self.target = target
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        server = socket.socket(socket.AF_INET6 if ":" in self.target.listen else socket.AF_INET)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.target.listen, self.target.port))
        server.listen(128)
        server.settimeout(0.5)
        self._server = server
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._server:
            self._server.close()
        if self._thread:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None

    def _accept_loop(self) -> None:
        assert self._server is not None
        while not self._stopping.is_set():
            try:
                client, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            client.settimeout(5)
            first = client.recv(1, socket.MSG_PEEK)
            if not first:
                return
            if first[0] == 4:
                # Mixed 入口仅保证 SOCKS5；明确拒绝 SOCKS4，避免按 HTTP 误处理或长时间等待。
                client.sendall(b"\x00\x5b\x00\x00\x00\x00\x00\x00")
                return
            target_port = self.target.socks_port if first[0] == 5 else self.target.http_port
            upstream = socket.create_connection(("127.0.0.1", target_port), timeout=5)
            client.setblocking(False)
            upstream.setblocking(False)
            self._relay(client, upstream)
        except OSError:
            pass
        finally:
            client.close()
            if upstream:
                upstream.close()

    def _relay(self, left: socket.socket, right: socket.socket) -> None:
        selector = selectors.DefaultSelector()
        selector.register(left, selectors.EVENT_READ, right)
        selector.register(right, selectors.EVENT_READ, left)
        try:
            while not self._stopping.is_set():
                events = selector.select(timeout=0.5)
                for key, _ in events:
                    destination: socket.socket = key.data
                    try:
                        data = key.fileobj.recv(65536)
                    except BlockingIOError:
                        continue
                    if not data:
                        return
                    destination.sendall(data)
        finally:
            selector.close()


class MixedProxyGroup:
    def __init__(self) -> None:
        self._proxies: list[MixedProxy] = []

    def start(self, targets: list[MixedTarget]) -> None:
        self.stop()
        started: list[MixedProxy] = []
        try:
            for target in targets:
                proxy = MixedProxy(target)
                proxy.start()
                started.append(proxy)
        except Exception:
            for proxy in started:
                proxy.stop()
            raise
        self._proxies = started

    def stop(self) -> None:
        for proxy in self._proxies:
            proxy.stop()
        self._proxies.clear()
