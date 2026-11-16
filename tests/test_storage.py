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
