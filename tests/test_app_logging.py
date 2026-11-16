from xray_ui.app_logging import configure_logging


def test_rotating_log_file(tmp_path):
    logger = configure_logging(tmp_path)
    logger.info("UI 测试操作")
    for handler in logger.handlers:
        handler.flush()
    assert "UI 测试操作" in (tmp_path / "xray-ui.log").read_text(encoding="utf-8")
