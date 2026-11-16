from xray_ui.updater import apply_proxy


def test_apply_proxy():
    url = "https://github.com/XTLS/Xray-core/releases/download/v1/Xray-windows-64.zip"
    assert apply_proxy(url, "") == url
    assert apply_proxy(url, "https://ghproxy.net/") == f"https://ghproxy.net/{url}"
