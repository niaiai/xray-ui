from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from .models import Node


def _b64decode(value: str) -> str:
    value = value.strip()
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")


def _b64encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _one(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def parse_share_link(link: str) -> Node:
    link = link.strip()
    scheme = link.partition(":")[0].lower()
    if scheme == "vmess":
        return _parse_vmess(link)
    if scheme == "ss":
        return _parse_shadowsocks(link)
    if scheme not in {"vless", "trojan", "socks", "http", "https"}:
        raise ValueError("不支持的分享链接协议")
    parsed = urlsplit(link)
    if not parsed.hostname or not parsed.port:
        raise ValueError("分享链接缺少服务器地址或端口")
    query = parse_qs(parsed.query)
    transport = _one(query, "type", "raw")
    if transport == "tcp":
        transport = "raw"
    protocol = "http" if scheme == "https" else scheme
    credential = unquote(parsed.username or "")
    if protocol in {"socks", "http"} and parsed.password is not None:
        credential = f"{credential}:{unquote(parsed.password)}"
    return Node(
        name=unquote(parsed.fragment) or f"{protocol}-{parsed.hostname}",
        protocol=protocol,
        address=parsed.hostname,
        port=parsed.port,
        credential=credential,
        security=_one(query, "security", "tls" if scheme == "https" else "none"),
        transport=transport,
        server_name=_one(query, "sni"),
        flow=_one(query, "flow"),
        path=unquote(_one(query, "path")),
        host=_one(query, "host"),
        public_key=_one(query, "pbk"),
        short_id=_one(query, "sid"),
        fingerprint=_one(query, "fp", "chrome"),
    )


def _parse_vmess(link: str) -> Node:
    try:
        value = json.loads(_b64decode(link.split("://", 1)[1]))
        transport = str(value.get("net", "raw"))
        if transport == "tcp":
            transport = "raw"
        return Node(
            name=str(value.get("ps") or f"vmess-{value['add']}"),
            protocol="vmess",
            address=str(value["add"]),
            port=int(value["port"]),
            credential=str(value["id"]),
            security=str(value.get("tls") or "none"),
            transport=transport,
            server_name=str(value.get("sni") or ""),
            path=str(value.get("path") or ""),
            host=str(value.get("host") or ""),
            fingerprint=str(value.get("fp") or "chrome"),
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("VMess 分享链接格式无效") from error


def _parse_shadowsocks(link: str) -> Node:
    raw = link.split("://", 1)[1]
    fragment = ""
    if "#" in raw:
        raw, fragment = raw.split("#", 1)
    raw = raw.split("?", 1)[0]
    if "@" not in raw:
        raw = _b64decode(raw)
    userinfo, endpoint = raw.rsplit("@", 1)
    if ":" not in userinfo:
        userinfo = _b64decode(userinfo)
    method, password = userinfo.split(":", 1)
    parsed = urlsplit(f"ss://host@{endpoint}")
    if not parsed.hostname or not parsed.port:
        raise ValueError("Shadowsocks 分享链接格式无效")
    return Node(
        name=unquote(fragment) or f"ss-{parsed.hostname}",
        protocol="shadowsocks",
        address=parsed.hostname,
        port=parsed.port,
        credential=unquote(password),
        method=unquote(method),
    )


def build_share_link(node: Node) -> str:
    if node.protocol == "vmess":
        value = {
            "v": "2",
            "ps": node.name,
            "add": node.address,
            "port": str(node.port),
            "id": node.credential,
            "aid": "0",
            "scy": "auto",
            "net": "tcp" if node.transport == "raw" else node.transport,
            "type": "none",
            "host": node.host,
            "path": node.path,
            "tls": "" if node.security == "none" else node.security,
            "sni": node.server_name,
            "fp": node.fingerprint,
        }
        return "vmess://" + _b64encode(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    if node.protocol == "shadowsocks":
        userinfo = _b64encode(f"{node.method}:{node.credential}")
        return f"ss://{userinfo}@{_endpoint(node.address, node.port)}#{quote(node.name)}"
    if node.protocol in {"socks", "http"}:
        username, separator, password = node.credential.partition(":")
        auth = quote(username, safe="")
        if separator:
            auth += f":{quote(password, safe='')}"
        if auth:
            auth += "@"
        return f"{node.protocol}://{auth}{_endpoint(node.address, node.port)}#{quote(node.name)}"

    query = {
        "encryption": "none",
        "security": node.security,
        "type": "tcp" if node.transport == "raw" else node.transport,
    }
    optional = {
        "sni": node.server_name,
        "flow": node.flow,
        "path": node.path,
        "host": node.host,
        "pbk": node.public_key,
        "sid": node.short_id,
        "fp": node.fingerprint,
    }
    query.update({key: value for key, value in optional.items() if value})
    return (
        f"{node.protocol}://{quote(node.credential, safe='')}@{_endpoint(node.address, node.port)}"
        f"?{urlencode(query)}#{quote(node.name)}"
    )


def _endpoint(address: str, port: int) -> str:
    host = f"[{address}]" if ":" in address and not address.startswith("[") else address
    return f"{host}:{port}"
