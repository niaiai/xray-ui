import json

from xray_ui.models import AppConfig, AppSettings, Inbound, Node
from xray_ui.storage import JsonConfigStore


def test_json_round_trip(tmp_path):
    node = Node("测试", "trojan", "server.example", 443, "password")
    original = AppConfig(nodes=[node], inbounds=[Inbound("入口", 10808, node.id)])
    store = JsonConfigStore(tmp_path / "config.json")
    store.save(original)
    loaded = store.load()
    assert loaded.to_dict() == original.to_dict()
    assert json.loads(store.path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_old_transport_names_are_migrated(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "name": "旧节点",
                        "protocol": "vless",
                        "address": "example.com",
                        "port": 443,
                        "credential": "uuid",
                        "transport": "ws",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert JsonConfigStore(path).load().nodes[0].transport == "websocket"


def test_old_per_inbound_custom_domains_are_migrated_to_global(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "inbounds": [
                    {
                        "name": "旧入口",
                        "port": 10808,
                        "node_id": "missing",
                        "route_mode": "custom",
                        "custom_domains": ["example.com"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = JsonConfigStore(path).load()
    assert config.inbounds[0].route_mode == "global"
    assert config.direct_domains == ["example.com"]


def test_ghproxy_is_enabled_by_default_and_empty_old_value_is_migrated():
    defaults = AppSettings.from_dict({})
    assert defaults.use_ghproxy is True
    assert defaults.ghproxy == "https://gh-proxy.com"
    migrated = AppSettings.from_dict({"ghproxy": ""})
    assert migrated.use_ghproxy is True
    assert migrated.ghproxy == "https://gh-proxy.com"
    assert migrated.dns_server == "https://1.1.1.1/dns-query"


def test_default_store_migrates_legacy_config_next_to_application(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_config = legacy_dir / "config.json"
    legacy_config.write_text('{"schema_version": 1, "nodes": []}', encoding="utf-8")
    monkeypatch.setattr("xray_ui.storage.application_dir", lambda: app_dir)
    monkeypatch.setattr("xray_ui.storage.default_data_dir", lambda: legacy_dir)
    store = JsonConfigStore()
    loaded = store.load()
    assert loaded.schema_version == 1
    assert store.path == app_dir / "config.json"
    assert store.path.exists()
    assert legacy_config.exists()
