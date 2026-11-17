from __future__ import annotations

from typing import Any

from .models import AppConfig, Node


def _unique_tag(name: str, used: set[str]) -> str:
    """保留配置名称作为标签，并为重名项追加可读序号。"""
    base = name.strip()
    tag = base
    number = 2
    while tag in used:
        tag = f"{base} ({number})"
        number += 1
    used.add(tag)
    return tag


def _stream_settings(node: Node) -> dict[str, Any]:
    stream: dict[str, Any] = {"method": node.transport, "security": node.security}
    if node.security == "tls":
        stream["tlsSettings"] = {
            "serverName": node.server_name or node.address,
            "allowInsecure": node.allow_insecure,
            "fingerprint": node.fingerprint,
        }
        if node.alpn:
            stream["tlsSettings"]["alpn"] = node.alpn
    elif node.security == "reality":
        stream["realitySettings"] = {
            "serverName": node.server_name,
            "fingerprint": node.fingerprint,
            "password": node.public_key,
            "shortId": node.short_id,
            "spiderX": node.spider_x,
        }
        if node.mldsa65_verify:
            stream["realitySettings"]["mldsa65Verify"] = node.mldsa65_verify
    if node.transport == "websocket":
        stream["wsSettings"] = {"path": node.path or "/", "host": node.host}
    elif node.transport == "grpc":
        stream["grpcSettings"] = {
            "serviceName": node.path,
            "authority": node.grpc_authority or node.host,
            "multiMode": node.grpc_multi_mode,
        }
    elif node.transport == "xhttp":
        settings: dict[str, Any] = {"path": node.path or "/", "host": node.host}
        if node.xhttp_mode:
            settings["mode"] = node.xhttp_mode
        if node.xhttp_extra:
            settings["extra"] = node.xhttp_extra
        stream["xhttpSettings"] = settings
    elif node.transport == "raw" and node.header_type != "none":
        stream["rawSettings"] = {"header": {"type": node.header_type}}
    return stream


def _outbound(node: Node, tag: str) -> dict[str, Any]:
    settings: dict[str, Any]
    if node.protocol == "vless":
        settings = {
            "address": node.address,
            "port": node.port,
            "id": node.credential,
            "encryption": node.encryption,
            "flow": node.flow,
        }
    elif node.protocol == "vmess":
        settings = {
            "address": node.address,
            "port": node.port,
            "id": node.credential,
            "security": node.vmess_security,
        }
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
        settings = {"address": node.address, "port": node.port}
        if node.credential:
            username, _, password = node.credential.partition(":")
            settings.update({"user": username, "pass": password})
    outbound: dict[str, Any] = {
        "tag": tag,
        "protocol": node.protocol,
        "settings": settings,
    }
    if node.protocol in {"vless", "vmess", "trojan", "shadowsocks", "socks", "http"}:
        outbound["streamSettings"] = _stream_settings(node)
    return outbound


def build_xray_config(config: AppConfig) -> dict[str, Any]:
    errors = config.validate()
    if errors:
        raise ValueError("；".join(errors))

    inbounds: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    balancers: list[dict[str, Any]] = []
    proxy_domains = [normalize_domain(value) for value in config.proxy_domains if value.strip()]
    used_outbound_tags = {"direct"}
    outbound_tags = {
        node.id: _unique_tag(node.name, used_outbound_tags) for node in config.nodes
    }
    used_inbound_tags: set[str] = set()
    used_balancer_tags: set[str] = set()
    for inbound in config.inbounds:
        tag = _unique_tag(inbound.name, used_inbound_tags)
        tags = [tag]
        users = (
            [{"user": inbound.auth_username, "pass": inbound.auth_password}]
            if inbound.auth_username
            else []
        )
        settings = (
            {
                "auth": "password" if users else "noauth",
                "users": users,
                "udp": True,
            }
            if inbound.protocol == "socks"
            else {"users": users}
        )
        inbounds.append(
            {
                "tag": tag,
                "listen": inbound.listen,
                "port": inbound.port,
                "protocol": inbound.protocol,
                "settings": settings,
                "sniffing": {
                    "enabled": True,
                    "destOverride": (
                        ["http", "tls", "quic"]
                        if inbound.protocol == "socks"
                        else ["http", "tls"]
                    ),
                    # 允许用 TLS SNI / HTTP Host 覆盖客户端传入的污染 IP。
                    "routeOnly": False,
                },
            }
        )
        if inbound.round_robin:
            balancer_tag = _unique_tag(f"{inbound.name} 轮询", used_balancer_tags)
            selected_ids = inbound.round_robin_node_ids or list(outbound_tags)
            balancers.append(
                {
                    "tag": balancer_tag,
                    "selector": [outbound_tags[node_id] for node_id in selected_ids],
                    "strategy": {"type": "roundRobin"},
                }
            )
            proxy_target = {"balancerTag": balancer_tag}
        else:
            proxy_target = {"outboundTag": outbound_tags[inbound.node_id]}
        if proxy_domains:
            rules.append(
                {
                    "type": "field",
                    "inboundTag": tags,
                    "domain": proxy_domains,
                    **proxy_target,
                }
            )
        if inbound.skip_private:
            rules.append(
                {
                    "type": "field",
                    "inboundTag": tags,
                    "ip": ["geoip:private"],
                    "outboundTag": "direct",
                }
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
                    "ip": ["geoip:cn"],
                    "outboundTag": "direct",
                }
            )
        rules.append({"type": "field", "inboundTag": tags, **proxy_target})

    runtime = {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": [_outbound(node, outbound_tags[node.id]) for node in config.nodes]
        + [{"tag": "direct", "protocol": "freedom", "settings": {}}],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": rules,
            "balancers": balancers,
        },
    }
    dns_server = config.settings.dns_server.strip()
    if dns_server:
        runtime["dns"] = {
            "servers": [dns_server],
            "queryStrategy": "UseIPv4",
            "disableFallback": True,
            "useSystemHosts": False,
        }
    return runtime


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
