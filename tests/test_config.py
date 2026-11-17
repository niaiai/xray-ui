from xray_ui.models import AppConfig, Inbound, Node
from xray_ui.xray_config import build_xray_config, normalize_domain


def sample_config(mode="global"):
    node = Node("节点 A", "vless", "example.com", 443, "uuid", security="tls")
    inbound = Inbound("入口 A", 10808, node.id, route_mode=mode)
    return AppConfig(nodes=[node], inbounds=[inbound]), node, inbound


def test_global_routes_both_internal_inbounds_to_selected_node():
    config, _node, _inbound = sample_config()
    result = build_xray_config(config)
    assert len(result["inbounds"]) == 1
    assert result["routing"]["rules"][-1]["outboundTag"] == "节点 A"
    assert result["routing"]["rules"][-1]["inboundTag"] == ["入口 A"]


def test_bypass_cn_rules_precede_default_node_rule():
    config, _node, _inbound = sample_config("bypass_cn")
    rules = build_xray_config(config)["routing"]["rules"]
    assert rules[0]["ip"] == ["geoip:private"]
    assert rules[1]["domain"] == ["geosite:cn"]
    assert rules[2]["ip"] == ["geoip:cn"]
    assert rules[3]["outboundTag"] == "节点 A"


def test_private_bypass_is_enabled_by_default_and_can_be_disabled():
    config, _node, inbound = sample_config()
    rules = build_xray_config(config)["routing"]["rules"]
    assert rules[0]["ip"] == ["geoip:private"]
    assert rules[0]["inboundTag"] == ["入口 A"]
    assert rules[1]["outboundTag"] == "节点 A"
    inbound.skip_private = False
    rules = build_xray_config(config)["routing"]["rules"]
    assert len(rules) == 1
    assert rules[0]["outboundTag"] == "节点 A"


def test_runtime_tags_use_configured_names():
    config, _, _inbound = sample_config()
    result = build_xray_config(config)
    assert [item["tag"] for item in result["inbounds"]] == ["入口 A"]
    assert result["outbounds"][0]["tag"] == "节点 A"


def test_inbound_overrides_polluted_ip_and_uses_trusted_dns():
    config, _, _inbound = sample_config()
    result = build_xray_config(config)
    assert result["inbounds"][0]["sniffing"]["routeOnly"] is False
    assert result["dns"] == {
        "servers": ["https://1.1.1.1/dns-query"],
        "queryStrategy": "UseIPv4",
        "disableFallback": True,
        "useSystemHosts": False,
    }


def test_trusted_dns_can_be_disabled():
    config, _, _inbound = sample_config()
    config.settings.dns_server = ""
    assert "dns" not in build_xray_config(config)


def test_duplicate_names_receive_readable_unique_tags():
    first = Node("同名", "vless", "one.example.com", 443, "uuid-1")
    second = Node("同名", "vless", "two.example.com", 443, "uuid-2")
    inbound = Inbound("入口", 10808, second.id)
    result = build_xray_config(AppConfig(nodes=[first, second], inbounds=[inbound]))
    assert [item["tag"] for item in result["outbounds"]] == ["同名", "同名 (2)", "direct"]
    assert result["routing"]["rules"][-1]["outboundTag"] == "同名 (2)"


def test_http_outbound_uses_current_flat_settings():
    node = Node("HTTP", "http", "proxy.example.com", 3128, "user:pass")
    inbound = Inbound("入口", 10808, node.id)
    outbound = build_xray_config(AppConfig(nodes=[node], inbounds=[inbound]))["outbounds"][0]
    assert outbound["settings"] == {
        "address": "proxy.example.com",
        "port": 3128,
        "user": "user",
        "pass": "pass",
    }


def test_socks_inbound_supports_password_authentication():
    config, _, inbound = sample_config()
    inbound.auth_username = "gec"
    inbound.auth_password = "secret"
    settings = build_xray_config(config)["inbounds"][0]["settings"]
    assert settings == {
        "auth": "password",
        "users": [{"user": "gec", "pass": "secret"}],
        "udp": True,
    }


def test_http_inbound_supports_basic_authentication():
    config, _, inbound = sample_config()
    inbound.protocol = "http"
    inbound.auth_username = "gec"
    inbound.auth_password = "secret"
    assert build_xray_config(config)["inbounds"][0]["settings"] == {
        "users": [{"user": "gec", "pass": "secret"}]
    }


def test_inbound_authentication_requires_both_username_and_password():
    config, _, inbound = sample_config()
    inbound.auth_username = "gec"
    assert config.validate() == ["入站 入口 A 的鉴权用户名和密码必须同时填写"]


def test_proxy_domains_are_normalized_and_override_bypass_rules():
    config, _, _inbound = sample_config("bypass_cn")
    config.proxy_domains = ["example.com", "*.example.org", "full:a.test"]
    rules = build_xray_config(config)["routing"]["rules"]
    assert rules[0]["domain"] == ["domain:example.com", "domain:example.org", "full:a.test"]
    assert rules[0]["inboundTag"] == ["入口 A"]
    assert rules[0]["outboundTag"] == "节点 A"
    assert rules[1]["ip"] == ["geoip:private"]
    assert normalize_domain("geosite:google") == "geosite:google"


def test_proxy_domains_use_inbound_round_robin_balancer():
    first = Node("一", "vless", "one.example.com", 443, "uuid-1")
    second = Node("二", "vless", "two.example.com", 443, "uuid-2")
    inbound = Inbound("轮询入口", 10808, first.id, round_robin=True)
    config = AppConfig(
        nodes=[first, second], inbounds=[inbound], proxy_domains=["google.com"]
    )
    rule = build_xray_config(config)["routing"]["rules"][0]
    assert rule["domain"] == ["domain:google.com"]
    assert rule["balancerTag"] == "轮询入口 轮询"


def test_inbounds_listen_on_configured_public_port():
    config, _, inbound = sample_config()
    inbound.protocol = "http"
    result = build_xray_config(config)
    assert len(result["inbounds"]) == 1
    assert result["inbounds"][0]["protocol"] == "http"
    assert result["inbounds"][0]["port"] == 10808
    assert result["routing"]["rules"][-1]["inboundTag"] == ["入口 A"]

    inbound.protocol = "socks"
    result = build_xray_config(config)
    assert len(result["inbounds"]) == 1
    assert result["inbounds"][0]["protocol"] == "socks"
    assert result["inbounds"][0]["port"] == 10808
    assert result["routing"]["rules"][-1]["inboundTag"] == ["入口 A"]


def test_inbound_can_round_robin_all_outbound_nodes():
    first = Node("一", "vless", "one.example.com", 443, "uuid-1", security="tls")
    second = Node("二", "trojan", "two.example.com", 443, "password", security="tls")
    inbound = Inbound("轮询入口", 10808, first.id, round_robin=True)
    result = build_xray_config(AppConfig(nodes=[first, second], inbounds=[inbound]))
    assert result["routing"]["balancers"] == [
        {
            "tag": "轮询入口 轮询",
            "selector": ["一", "二"],
            "strategy": {"type": "roundRobin"},
        }
    ]
    assert result["routing"]["rules"][-1]["balancerTag"] == "轮询入口 轮询"


def test_inbound_can_round_robin_selected_nodes_only():
    nodes = [
        Node("一", "vless", "one.example.com", 443, "uuid-1", security="tls"),
        Node("二", "vless", "two.example.com", 443, "uuid-2", security="tls"),
        Node("三", "trojan", "three.example.com", 443, "password", security="tls"),
    ]
    inbound = Inbound(
        "部分轮询",
        10808,
        nodes[0].id,
        round_robin=True,
        round_robin_node_ids=[nodes[0].id, nodes[2].id],
    )
    result = build_xray_config(AppConfig(nodes=nodes, inbounds=[inbound]))
    assert result["routing"]["balancers"][0]["selector"] == ["一", "三"]
