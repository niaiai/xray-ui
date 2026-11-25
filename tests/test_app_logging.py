import logging

from xray_ui.app_logging import configure_logging


def test_rotating_log_file_defaults_to_application_log_directory(tmp_path, monkeypatch):
    logger = logging.getLogger("xray_ui")
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    monkeypatch.setattr("xray_ui.app_logging.application_dir", lambda: tmp_path)
    logger = configure_logging()
    logger.info("UI 测试操作")
    for handler in logger.handlers:
        handler.flush()
    assert "UI 测试操作" in (tmp_path / "log" / "xray-ui.log").read_text(
        encoding="utf-8"
    )
