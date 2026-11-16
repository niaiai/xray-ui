from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .app_logging import configure_logging
from .models import AppConfig, MixedInbound, Node
from .node_tester import test_node
from .process import XrayProcessManager
from .share_links import build_share_link, parse_share_link
from .storage import JsonConfigStore, default_data_dir
from .updater import XrayUpdater
from .windows import set_start_with_windows


class UpdateWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, updater: XrayUpdater) -> None:
        super().__init__()
        self.updater = updater

    def run(self) -> None:
        try:
            release = self.updater.latest()
            if self.updater.installed_version() == release.version:
                self.done.emit(f"当前已是最新版本 {release.version}")
                return
            self.updater.install(release)
            self.done.emit(f"Xray-core 已更新到 {release.version}")
        except Exception as error:
            self.failed.emit(str(error))


class NodeTestWorker(QThread):
    done = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self, node: Node, xray_dir: Path) -> None:
        super().__init__()
        self.node = node
        self.xray_dir = xray_dir

    def run(self) -> None:
        try:
            result = test_node(self.node, self.xray_dir)
            self.done.emit(self.node.name, result.elapsed_ms)
        except Exception as error:
            self.failed.emit(self.node.name, str(error))


class LogBridge(QObject):
    message = Signal(str)


class NodeDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增节点")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.protocol = QLineEdit("vless")
        self.address = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(443)
        self.credential = QLineEdit()
        self.security = QLineEdit("tls")
        self.transport = QLineEdit("raw")
        self.server_name = QLineEdit()
        for label, widget in (
            ("名称", self.name),
            ("协议", self.protocol),
            ("地址", self.address),
            ("端口", self.port),
            ("UUID/密码", self.credential),
            ("安全", self.security),
            ("传输", self.transport),
            ("SNI", self.server_name),
        ):
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def value(self) -> Node:
        return Node(
            name=self.name.text().strip(),
            protocol=self.protocol.text().strip().lower(),
            address=self.address.text().strip(),
            port=self.port.value(),
            credential=self.credential.text().strip(),
            security=self.security.text().strip().lower(),
            transport=self.transport.text().strip().lower(),
            server_name=self.server_name.text().strip(),
        )


class InboundDialog(QDialog):
    MODES: ClassVar = {"全局": "global", "跳过 CN": "bypass_cn", "自定义域名直连": "custom"}

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("新增 Mixed 入站")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.listen = QLineEdit("127.0.0.1")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(10808)
        self.node = QLineEdit(config.nodes[0].name if config.nodes else "")
        self.mode = QLineEdit("全局")
        self.domains = QTextEdit()
        self.domains.setPlaceholderText("每行一个域名，例如 example.com 或 *.example.com")
        for label, widget in (
            ("名称", self.name),
            ("监听地址", self.listen),
            ("端口", self.port),
            ("出口节点名称", self.node),
            ("路由模式", self.mode),
            ("直连域名", self.domains),
        ):
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def value(self) -> MixedInbound:
        selected = next(
            (node for node in self.config.nodes if node.name == self.node.text().strip()), None
        )
        if not selected:
            raise ValueError("找不到指定的出口节点")
        mode_text = self.mode.text().strip()
        mode = self.MODES.get(mode_text, mode_text)
        if mode not in self.MODES.values():
            raise ValueError("路由模式只能是：全局、跳过 CN、自定义域名直连")
        return MixedInbound(
            name=self.name.text().strip(),
            listen=self.listen.text().strip(),
            port=self.port.value(),
            node_id=selected.id,
            route_mode=mode,
            custom_domains=[
                line.strip() for line in self.domains.toPlainText().splitlines() if line.strip()
            ],
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = JsonConfigStore()
        self.logger = configure_logging()
        self.config = self.store.load()
        if not self.config.settings.xray_dir:
            self.config.settings.xray_dir = str(default_data_dir() / "core")
        self.log_bridge = LogBridge()
        self.log_bridge.message.connect(self.append_log)
        self.manager = XrayProcessManager(self.log_bridge.message.emit)
        self.worker: UpdateWorker | None = None
        self.test_worker: NodeTestWorker | None = None
        self.exiting = False
        self.setWindowTitle("Xray UI")
        self.resize(920, 620)
        self._build_ui()
        self._build_tray()
        self.refresh()
        self.audit("应用启动")
        QTimer.singleShot(0, self._after_startup)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        controls = QHBoxLayout()
        self.status = QLabel("已停止")
        self.start_button = QPushButton("启动")
        self.stop_button = QPushButton("停止")
        update_button = QPushButton("下载/更新 Xray")
        self.start_button.clicked.connect(self.start_xray)
        self.stop_button.clicked.connect(self.stop_xray)
        update_button.clicked.connect(self.update_xray)
        controls.addWidget(self.status)
        controls.addStretch()
        controls.addWidget(update_button)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)

        tabs = QTabWidget()
        self.node_table = QTableWidget(0, 4)
        self.node_table.setHorizontalHeaderLabels(["名称", "协议", "地址", "端口"])
        self.inbound_table = QTableWidget(0, 5)
        self.inbound_table.setHorizontalHeaderLabels(["名称", "监听", "端口", "出口", "路由"])
        tabs.addTab(
            self._table_page(
                self.node_table,
                self.add_node,
                self.remove_node,
                (
                    ("从链接导入", self.import_node),
                    ("复制分享链接", self.copy_node_link),
                    ("测试节点", self.test_selected_node),
                ),
            ),
            "节点",
        )
        tabs.addTab(
            self._table_page(self.inbound_table, self.add_inbound, self.remove_inbound),
            "Mixed 入站",
        )
        tabs.addTab(self._settings_page(), "设置")
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        tabs.addTab(self.logs, "日志")
        layout.addWidget(tabs)
        self.setCentralWidget(central)

    def _table_page(self, table, add, remove, extra_actions=()) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(table)
        row = QHBoxLayout()
        add_button, remove_button = QPushButton("新增"), QPushButton("删除")
        add_button.clicked.connect(add)
        remove_button.clicked.connect(remove)
        row.addStretch()
        for text, action in extra_actions:
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
        row.addWidget(add_button)
        row.addWidget(remove_button)
        layout.addLayout(row)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.xray_dir = QLineEdit(self.config.settings.xray_dir)
        self.ghproxy = QLineEdit(self.config.settings.ghproxy)
        self.ghproxy.setPlaceholderText("例如 https://ghproxy.net，留空为直连")
        self.auto_update = QCheckBox()
        self.auto_update.setChecked(self.config.settings.auto_update)
        self.auto_start_xray = QCheckBox()
        self.auto_start_xray.setChecked(self.config.settings.auto_start_xray)
        self.start_with_windows = QCheckBox()
        self.start_with_windows.setChecked(self.config.settings.start_with_windows)
        save = QPushButton("保存设置")
        save.clicked.connect(self.save_settings)
        form.addRow("Xray 目录", self.xray_dir)
        form.addRow("ghproxy", self.ghproxy)
        form.addRow("启动时检查更新", self.auto_update)
        form.addRow("启动应用后运行 Xray", self.auto_start_xray)
        form.addRow("开机启动", self.start_with_windows)
        form.addRow(save)
        return page

    def _build_tray(self) -> None:
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Xray UI")
        menu = self.tray.contextMenu()
        if menu is None:
            from PySide6.QtWidgets import QMenu

            menu = QMenu(self)
            self.tray.setContextMenu(menu)
        show_action = QAction("显示", self)
        start_action = QAction("启动 Xray", self)
        stop_action = QAction("停止 Xray", self)
        exit_action = QAction("退出", self)
        show_action.triggered.connect(self._show_window)
        start_action.triggered.connect(self.start_xray)
        stop_action.triggered.connect(self.stop_xray)
        exit_action.triggered.connect(self._exit_app)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(start_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.activated.connect(
            lambda reason: (
                self._show_window()
                if reason == QSystemTrayIcon.ActivationReason.DoubleClick
                else None
            )
        )
        self.tray.show()

    def _after_startup(self) -> None:
        if self.config.settings.auto_update:
            self.audit("自动检查 Xray 更新")
            self.update_xray()
        if self.config.settings.auto_start_xray:
            self.audit("自动启动 Xray")
            self.start_xray()

    def refresh(self) -> None:
        self.node_table.setRowCount(len(self.config.nodes))
        for row, node in enumerate(self.config.nodes):
            for column, value in enumerate(
                (node.name, node.protocol, node.address, str(node.port))
            ):
                self.node_table.setItem(row, column, QTableWidgetItem(value))
        names = {node.id: node.name for node in self.config.nodes}
        self.inbound_table.setRowCount(len(self.config.inbounds))
        for row, item in enumerate(self.config.inbounds):
            values = (
                item.name,
                item.listen,
                str(item.port),
                names.get(item.node_id, "无效"),
                item.route_mode,
            )
            for column, value in enumerate(values):
                self.inbound_table.setItem(row, column, QTableWidgetItem(value))

    def add_node(self) -> None:
        dialog = NodeDialog(self)
        if dialog.exec():
            self.config.nodes.append(dialog.value())
            self._save_refresh()
            self.audit(f"新增节点：{self.config.nodes[-1].name}")

    def import_node(self) -> None:
        link, accepted = QInputDialog.getMultiLineText(self, "导入分享链接", "每行一个分享链接：")
        if not accepted:
            return
        imported: list[Node] = []
        errors: list[str] = []
        for number, value in enumerate(link.splitlines(), start=1):
            if not value.strip():
                continue
            try:
                imported.append(parse_share_link(value))
            except ValueError as error:
                errors.append(f"第 {number} 行：{error}")
        if imported:
            self.config.nodes.extend(imported)
            self._save_refresh()
            self.audit(f"从分享链接导入 {len(imported)} 个节点")
        if errors:
            self.error("\n".join(errors))

    def copy_node_link(self) -> None:
        row = self.node_table.currentRow()
        if row < 0:
            self.error("请先选择节点")
            return
        node = self.config.nodes[row]
        QApplication.clipboard().setText(build_share_link(node))
        self.audit(f"复制节点分享链接：{node.name}")
        self.tray.showMessage("Xray UI", "分享链接已复制到剪贴板")

    def test_selected_node(self) -> None:
        row = self.node_table.currentRow()
        if row < 0:
            self.error("请先选择节点")
            return
        if self.test_worker and self.test_worker.isRunning():
            self.error("已有节点正在测试")
            return
        node = self.config.nodes[row]
        self.audit(f"开始测试节点：{node.name}")
        self.test_worker = NodeTestWorker(node, Path(self.config.settings.xray_dir))
        self.test_worker.done.connect(self._node_test_done)
        self.test_worker.failed.connect(self._node_test_failed)
        self.test_worker.start()

    def _node_test_done(self, name: str, elapsed_ms: int) -> None:
        message = f"节点 {name} 测试成功：{elapsed_ms} ms"
        self.audit(message)
        QMessageBox.information(self, "节点测试", message)

    def _node_test_failed(self, name: str, reason: str) -> None:
        self.error(f"节点 {name} 测试失败：{reason}")

    def remove_node(self) -> None:
        row = self.node_table.currentRow()
        if row >= 0:
            node_id = self.config.nodes[row].id
            if any(item.node_id == node_id for item in self.config.inbounds):
                self.error("该节点仍被 Mixed 入站使用")
                return
            self.config.nodes.pop(row)
            self._save_refresh()
            self.audit("删除节点")

    def add_inbound(self) -> None:
        if not self.config.nodes:
            self.error("请先新增出口节点")
            return
        dialog = InboundDialog(self.config, self)
        if dialog.exec():
            try:
                self.config.inbounds.append(dialog.value())
                self._save_refresh()
                self.audit(f"新增 Mixed 入站：{self.config.inbounds[-1].name}")
            except ValueError as error:
                self.error(str(error))

    def remove_inbound(self) -> None:
        row = self.inbound_table.currentRow()
        if row >= 0:
            self.config.inbounds.pop(row)
            self._save_refresh()
            self.audit("删除 Mixed 入站")

    def save_settings(self) -> None:
        self.config.settings.xray_dir = self.xray_dir.text().strip()
        self.config.settings.ghproxy = self.ghproxy.text().strip()
        self.config.settings.auto_update = self.auto_update.isChecked()
        self.config.settings.auto_start_xray = self.auto_start_xray.isChecked()
        self.config.settings.start_with_windows = self.start_with_windows.isChecked()
        try:
            set_start_with_windows(self.config.settings.start_with_windows)
        except OSError as error:
            self.error(f"开机启动设置失败：{error}")
            return
        self._save_refresh()
        self.audit("保存应用设置")

    def start_xray(self) -> None:
        try:
            self.store.save(self.config)
            self.manager.start(self.config, Path(self.config.settings.xray_dir))
            self.status.setText("运行中")
            self.audit("启动 Xray")
        except Exception as error:
            self.error(str(error))

    def stop_xray(self) -> None:
        self.manager.stop()
        self.status.setText("已停止")
        self.audit("停止 Xray")

    def update_xray(self) -> None:
        if self.worker and self.worker.isRunning():
            self.audit("忽略重复的 Xray 更新请求")
            return
        self.audit("检查并更新 Xray")
        updater = XrayUpdater(Path(self.xray_dir.text().strip()), self.ghproxy.text().strip())
        self.worker = UpdateWorker(updater)
        self.worker.done.connect(self._update_done)
        self.worker.failed.connect(self.error)
        self.worker.start()

    def _save_refresh(self) -> None:
        try:
            self.store.save(self.config)
            self.refresh()
        except ValueError as error:
            self.error(str(error))

    def append_log(self, text: str) -> None:
        self.logs.append(f"[{self._log_time()}] [XRAY] {text}")
        self.logger.info("[XRAY] %s", text)

    def audit(self, text: str) -> None:
        line = f"[{self._log_time()}] [UI] {text}"
        self.logs.append(line)
        self.logger.info("[UI] %s", text)

    @staticmethod
    def _log_time() -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    def _update_done(self, text: str) -> None:
        self.audit(text)
        QMessageBox.information(self, "完成", text)

    def error(self, text: str) -> None:
        self.logger.error("[UI] %s", text)
        if hasattr(self, "logs"):
            self.logs.append(f"[{self._log_time()}] [错误] {text}")
        QMessageBox.critical(self, "错误", text)

    def closeEvent(self, event) -> None:
        if not self.exiting and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.audit("窗口最小化到系统托盘")
            self.tray.showMessage("Xray UI", "程序仍在托盘运行")
            return
        self.manager.stop()
        self.audit("应用退出")
        event.accept()

    def _show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.audit("从系统托盘显示窗口")

    def _exit_app(self) -> None:
        self.exiting = True
        self.close()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
