import pytest

from xray_ui.models import AppConfig, Inbound, Node
from xray_ui.share_links import build_share_link, parse_share_link
from xray_ui.xray_config import build_xray_config


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


def test_https_proxy_share_link_round_trip():
    node = Node(
        "HTTPS 代理", "http", "proxy.example.com", 443, "user:password", security="tls"
    )
    link = build_share_link(node)
    assert link.startswith("https://")
    parsed = parse_share_link(link)
    assert parsed.protocol == "http"
    assert parsed.security == "tls"


def test_parse_multiple_common_vless_parameters():
    link = (
        "vless://uuid@example.com:443?security=reality&type=tcp&sni=www.example.com"
        "&fp=chrome&pbk=key&sid=abcd&flow=xtls-rprx-vision#Hong%20Kong"
    )
    node = parse_share_link(link)
    assert node.name == "Hong Kong"
    assert node.transport == "raw"
    assert node.public_key == "key"


def test_vless_import_preserves_transport_and_security_parameters():
    link = (
        "vless://uuid@example.com:443?encryption=mlkem768x25519plus.native.0rtt.key"
        "&security=reality&type=grpc&sni=www.example.com&fp=firefox&pbk=password"
        "&sid=abcd&spx=%2Fspider&pqv=verify&serviceName=svc&path=svc"
        "&authority=grpc.example.com&mode=multi&alpn=h2%2Chttp%2F1.1#node"
    )
    node = parse_share_link(link)
    assert node.encryption.startswith("mlkem768x25519plus")
    assert node.transport == "grpc"
    assert node.grpc_authority == "grpc.example.com"
    assert node.grpc_multi_mode is True
    assert node.spider_x == "/spider"
    assert node.mldsa65_verify == "verify"
    assert node.alpn == ["h2", "http/1.1"]
    inbound = Inbound("test", 1080, node.id)
    outbound = build_xray_config(AppConfig(nodes=[node], inbounds=[inbound]))["outbounds"][0]
    assert outbound["settings"]["encryption"] == node.encryption
    assert outbound["streamSettings"]["method"] == "grpc"
    assert outbound["streamSettings"]["realitySettings"]["password"] == "password"
    assert outbound["streamSettings"]["grpcSettings"]["multiMode"] is True


def test_vmess_ws_import_uses_current_xray_method():
    original = Node(
        "ws",
        "vmess",
        "example.com",
        443,
        "uuid",
        security="tls",
        transport="websocket",
        path="/ws",
        host="cdn.example.com",
        vmess_security="chacha20-poly1305",
        allow_insecure=True,
        alpn=["http/1.1"],
    )
    node = parse_share_link(build_share_link(original))
    inbound = Inbound("test", 1080, node.id)
    outbound = build_xray_config(AppConfig(nodes=[node], inbounds=[inbound]))["outbounds"][0]
    assert node.transport == "websocket"
    assert outbound["settings"]["security"] == "chacha20-poly1305"
    assert outbound["streamSettings"]["method"] == "websocket"
    assert outbound["streamSettings"]["wsSettings"]["host"] == "cdn.example.com"
    assert outbound["streamSettings"]["tlsSettings"]["allowInsecure"] is True


def test_xhttp_extra_round_trip():
    node = Node(
        "xhttp",
        "vless",
        "example.com",
        443,
        "uuid",
        security="tls",
        transport="xhttp",
        path="/x",
        host="cdn.example.com",
        xhttp_mode="stream-up",
        xhttp_extra={"downloadSettings": {"address": "down.example.com"}},
    )
    parsed = parse_share_link(build_share_link(node))
    assert parsed.xhttp_mode == "stream-up"
    assert parsed.xhttp_extra == node.xhttp_extra
