from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import AppConfig, Node


@dataclass(frozen=True, slots=True)
class InternalPorts:
    socks: int
    http: int


def _stream_settings(node: Node) -> dict[str, Any]:
    stream: dict[str, Any] = {"network": node.transport, "security": node.security}
    if node.security == "tls":
        stream["tlsSettings"] = {
            "serverName": node.server_name or node.address,
            "fingerprint": node.fingerprint,
        }
    elif node.security == "reality":
        stream["realitySettings"] = {
            "serverName": node.server_name,
            "fingerprint": node.fingerprint,
            "publicKey": node.public_key,
            "shortId": node.short_id,
        }
    if node.transport == "websocket":
        stream["wsSettings"] = {"path": node.path or "/", "headers": {"Host": node.host}}
    elif node.transport == "grpc":
        stream["grpcSettings"] = {"serviceName": node.path.lstrip("/")}
    elif node.transport == "xhttp":
        stream["xhttpSettings"] = {"path": node.path or "/", "host": node.host}
    return stream


def _outbound(node: Node, tag: str) -> dict[str, Any]:
    settings: dict[str, Any]
    if node.protocol == "vless":
        settings = {
            "address": node.address,
            "port": node.port,
            "id": node.credential,
            "encryption": "none",
            "flow": node.flow,
        }
    elif node.protocol == "vmess":
        settings = {"address": node.address, "port": node.port, "id": node.credential}
    elif node.protocol == "trojan":
        settings = {"address": node.address, "port": node.port, "password": node.credential}
    elif node.protocol == "shadowsocks":
        settings = {
            "address": node.address,
            "port": node.port,
            "password": node.credential,
            "method": node.method,
        }
    else:
        settings = {"servers": [{"address": node.address, "port": node.port, "users": []}]}
        if node.credential:
            username, _, password = node.credential.partition(":")
            settings["servers"][0]["users"] = [{"user": username, "pass": password}]
    outbound: dict[str, Any] = {
        "tag": tag,
        "protocol": node.protocol,
        "settings": settings,
    }
    if node.protocol in {"vless", "vmess", "trojan", "shadowsocks"}:
        outbound["streamSettings"] = _stream_settings(node)
    return outbound


def build_xray_config(
    config: AppConfig, internal_ports: dict[str, InternalPorts]
) -> dict[str, Any]:
    errors = config.validate()
    if errors:
        raise ValueError("；".join(errors))

    inbounds: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    outbound_tags = {node.id: f"out-{index}" for index, node in enumerate(config.nodes, 1)}
    for index, inbound in enumerate(config.inbounds, 1):
        ports = internal_ports[inbound.id]
        tags = [f"in-{index}-s", f"in-{index}-h"]
        inbounds.extend(
            [
                {
                    "tag": tags[0],
                    "listen": "127.0.0.1",
                    "port": ports.socks,
                    "protocol": "socks",
                    "settings": {"udp": True},
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls", "quic"],
                        "routeOnly": True,
                    },
                },
                {
                    "tag": tags[1],
                    "listen": "127.0.0.1",
                    "port": ports.http,
                    "protocol": "http",
                    "settings": {},
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls"],
                        "routeOnly": True,
                    },
                },
            ]
        )
        if inbound.route_mode == "bypass_cn":
            rules.append(
                {
                    "type": "field",
                    "inboundTag": tags,
                    "domain": ["geosite:cn"],
                    "outboundTag": "direct",
                }
            )
            rules.append(
                {
                    "type": "field",
                    "inboundTag": tags,
                    "ip": ["geoip:private", "geoip:cn"],
                    "outboundTag": "direct",
                }
            )
        elif inbound.route_mode == "custom" and inbound.custom_domains:
            domains = [normalize_domain(value) for value in inbound.custom_domains if value.strip()]
            rules.append(
                {"type": "field", "inboundTag": tags, "domain": domains, "outboundTag": "direct"}
            )
        rules.append(
            {
                "type": "field",
                "inboundTag": tags,
                "outboundTag": outbound_tags[inbound.node_id],
            }
        )

    return {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": [_outbound(node, outbound_tags[node.id]) for node in config.nodes]
        + [{"tag": "direct", "protocol": "freedom", "settings": {}}],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": rules},
    }


def normalize_domain(value: str) -> str:
    value = value.strip()
    if any(
        value.startswith(prefix)
        for prefix in ("domain:", "full:", "keyword:", "regexp:", "geosite:")
    ):
        return value
    if value.startswith("*."):
        return f"domain:{value[2:]}"
    return f"domain:{value}"
