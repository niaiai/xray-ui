import json

from xray_ui.models import AppConfig, MixedInbound, Node
from xray_ui.storage import JsonConfigStore


def test_json_round_trip(tmp_path):
    node = Node("测试", "trojan", "server.example", 443, "password")
    original = AppConfig(nodes=[node], inbounds=[MixedInbound("入口", 10808, node.id)])
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
