import socket
import threading

from xray_ui.mixed_proxy import MixedProxy, MixedTarget


def test_socks4_is_rejected_explicitly():
    proxy = MixedProxy(MixedTarget("127.0.0.1", 10808, 30001, 30002))
    client, server = socket.socketpair()
    thread = threading.Thread(target=proxy._handle, args=(server,))
    thread.start()
    client.sendall(b"\x04")
    assert client.recv(8) == b"\x00\x5b\x00\x00\x00\x00\x00\x00"
    thread.join(timeout=1)
    client.close()
