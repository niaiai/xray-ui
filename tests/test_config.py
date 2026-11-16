from xray_ui.models import AppConfig, MixedInbound, Node
from xray_ui.xray_config import InternalPorts, build_xray_config, normalize_domain


def sample_config(mode="global", domains=None):
    node = Node("节点 A", "vless", "example.com", 443, "uuid", security="tls")
    inbound = MixedInbound("入口 A", 10808, node.id, route_mode=mode, custom_domains=domains or [])
    return AppConfig(nodes=[node], inbounds=[inbound]), node, inbound


def test_global_routes_both_internal_inbounds_to_selected_node():
    config, _node, inbound = sample_config()
    result = build_xray_config(config, {inbound.id: InternalPorts(31001, 31002)})
    assert len(result["inbounds"]) == 2
    assert result["routing"]["rules"][-1]["outboundTag"] == "out-1"
    assert len(result["routing"]["rules"][-1]["inboundTag"]) == 2


def test_bypass_cn_rules_precede_default_node_rule():
    config, _node, inbound = sample_config("bypass_cn")
    rules = build_xray_config(config, {inbound.id: InternalPorts(31001, 31002)})["routing"]["rules"]
    assert rules[0]["domain"] == ["geosite:cn"]
    assert rules[1]["ip"] == ["geoip:private", "geoip:cn"]
    assert rules[2]["outboundTag"] == "out-1"


def test_runtime_tags_are_short_and_stable():
    config, _, inbound = sample_config()
    result = build_xray_config(config, {inbound.id: InternalPorts(31001, 31002)})
    assert [item["tag"] for item in result["inbounds"]] == ["in-1-s", "in-1-h"]
    assert result["outbounds"][0]["tag"] == "out-1"


def test_custom_domains_are_normalized():
    config, _, inbound = sample_config("custom", ["example.com", "*.example.org", "full:a.test"])
    rules = build_xray_config(config, {inbound.id: InternalPorts(31001, 31002)})["routing"]["rules"]
    assert rules[0]["domain"] == ["domain:example.com", "domain:example.org", "full:a.test"]
    assert normalize_domain("geosite:google") == "geosite:google"
