import pytest

from xray_ui.updater import ReleaseInfo, XrayUpdater, apply_proxy


def test_apply_proxy():
    url = "https://github.com/XTLS/Xray-core/releases/download/v1/Xray-windows-64.zip"
    assert apply_proxy(url, "") == url
    assert apply_proxy(url, "https://ghproxy.net/") == f"https://ghproxy.net/{url}"


def test_install_reports_invalid_proxy_response(tmp_path, monkeypatch):
    updater = XrayUpdater(tmp_path / "core", "https://proxy.example")

    def fake_download(url, destination, progress):
        destination.write_text("proxy error page", encoding="utf-8")

    monkeypatch.setattr(updater, "_download", fake_download)
    release = ReleaseInfo("v1", "https://github.com/example.zip", "Xray-windows-64.zip")
    with pytest.raises(RuntimeError, match="不是有效的 Xray ZIP"):
        updater.install(release)
