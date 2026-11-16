import pytest

from xray_ui.models import Node
from xray_ui.share_links import build_share_link, parse_share_link


@pytest.mark.parametrize(
    "node",
    [
        Node(
            "VLESS 节点",
            "vless",
            "vless.example.com",
            443,
            "c48619b2-2c7e-4e2a-b52f-123456789abc",
            security="reality",
            transport="raw",
            server_name="www.example.com",
            flow="xtls-rprx-vision",
            public_key="public-key",
            short_id="1234abcd",
        ),
        Node(
            "VMess 节点",
            "vmess",
            "vmess.example.com",
            443,
            "c48619b2-2c7e-4e2a-b52f-123456789abc",
            security="tls",
            transport="websocket",
            path="/ws",
            host="cdn.example.com",
        ),
        Node("Trojan 节点", "trojan", "trojan.example.com", 443, "p@ss word", security="tls"),
        Node(
            "SS 节点",
            "shadowsocks",
            "ss.example.com",
            8388,
            "password",
            method="aes-256-gcm",
        ),
        Node("SOCKS 节点", "socks", "127.0.0.1", 1080, "user:password"),
        Node("HTTP 节点", "http", "127.0.0.1", 8080, "user:password"),
    ],
)
def test_share_link_round_trip(node):
    parsed = parse_share_link(build_share_link(node))
    assert parsed.name == node.name
    assert parsed.protocol == node.protocol
    assert parsed.address == node.address
    assert parsed.port == node.port
    assert parsed.credential == node.credential


def test_parse_multiple_common_vless_parameters():
    link = (
        "vless://uuid@example.com:443?security=reality&type=tcp&sni=www.example.com"
        "&fp=chrome&pbk=key&sid=abcd&flow=xtls-rprx-vision#Hong%20Kong"
    )
    node = parse_share_link(link)
    assert node.name == "Hong Kong"
    assert node.transport == "raw"
    assert node.public_key == "key"
