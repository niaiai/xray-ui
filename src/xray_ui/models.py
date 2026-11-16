from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4

RouteMode = Literal["global", "bypass_cn", "custom"]
Protocol = Literal["vless", "vmess", "trojan", "shadowsocks", "socks", "http"]


def new_id() -> str:
    return uuid4().hex


@dataclass(slots=True)
class Node:
    name: str
    protocol: Protocol
    address: str
    port: int
    credential: str = ""
    security: str = "none"
    transport: str = "raw"
    server_name: str = ""
    flow: str = ""
    path: str = ""
    host: str = ""
    public_key: str = ""
    short_id: str = ""
    fingerprint: str = "chrome"
    method: str = "aes-128-gcm"
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Node:
        return cls(**value)


@dataclass(slots=True)
class MixedInbound:
    name: str
    port: int
    node_id: str
    listen: str = "127.0.0.1"
    route_mode: RouteMode = "global"
    custom_domains: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MixedInbound:
        return cls(**value)


@dataclass(slots=True)
class AppSettings:
    xray_dir: str = ""
    ghproxy: str = ""
    auto_update: bool = True
    auto_start_xray: bool = False
    start_with_windows: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AppSettings:
        return cls(**value)


@dataclass(slots=True)
class AppConfig:
    schema_version: int = 1
    settings: AppSettings = field(default_factory=AppSettings)
    nodes: list[Node] = field(default_factory=list)
    inbounds: list[MixedInbound] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AppConfig:
        return cls(
            schema_version=int(value.get("schema_version", 1)),
            settings=AppSettings.from_dict(value.get("settings", {})),
            nodes=[Node.from_dict(item) for item in value.get("nodes", [])],
            inbounds=[MixedInbound.from_dict(item) for item in value.get("inbounds", [])],
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        node_ids = {node.id for node in self.nodes}
        endpoints: set[tuple[str, int]] = set()
        for node in self.nodes:
            if not node.name.strip() or not node.address.strip():
                errors.append("节点名称和地址不能为空")
            if not 1 <= node.port <= 65535:
                errors.append(f"节点 {node.name} 的端口无效")
        for inbound in self.inbounds:
            endpoint = (inbound.listen, inbound.port)
            if endpoint in endpoints:
                errors.append(f"Mixed 入站端口重复：{inbound.listen}:{inbound.port}")
            endpoints.add(endpoint)
            if not 1 <= inbound.port <= 65535:
                errors.append(f"入站 {inbound.name} 的端口无效")
            if inbound.node_id not in node_ids:
                errors.append(f"入站 {inbound.name} 未绑定有效节点")
        return errors
