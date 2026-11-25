from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
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
from .models import AppConfig, Inbound, Node
from .node_tester import test_node
from .process import XrayProcessManager
from .share_links import build_share_link, parse_share_link
from .storage import JsonConfigStore, application_dir, default_data_dir
from .updater import XrayUpdater
from .windows import set_start_with_windows


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", application_dir()))
    return base / relative


class UpdateWorker(QThread):
    done = Signal(str)
    failed = Signal(str)
    status = Signal(str)
    progress = Signal(int)

    def __init__(self, updater: XrayUpdater) -> None:
        super().__init__()
        self.updater = updater

    def run(self) -> None:
        try:
            first_install = not (self.updater.xray_dir / "xray.exe").exists()
            if first_install:
                self.status.emit("未检测到 Xray-core，准备首次下载")
            self.status.emit("正在获取 Xray-core 最新版本信息")
            release = self.updater.latest()
            installed = self.updater.installed_version()
            self.status.emit(f"最新版本：{release.version}")
            if not first_install and installed == release.version:
                self.done.emit(f"当前已是最新版本 {release.version}")
                return
            action = "下载" if first_install else "更新"
            self.status.emit(f"开始{action} {release.asset_name}")
            last_reported = -10

            def report_progress(value: int) -> None:
                nonlocal last_reported
                bucket = value // 10 * 10
                if bucket > last_reported:
                    last_reported = bucket
                    self.progress.emit(value)

            self.updater.install(release, report_progress)
            self.status.emit("下载包校验、解压及文件安装完成")
            self.done.emit(
                f"Xray-core 已安装 {release.version}"
                if first_install
                else f"Xray-core 已更新到 {release.version}"
            )
        except Exception as error:
            self.failed.emit(str(error))


class NodeTestWorker(QThread):
    done = Signal(str, str, int)
    failed = Signal(str, str, str)

    def __init__(self, node: Node, xray_dir: Path) -> None:
        super().__init__()
        self.node = node
        self.xray_dir = xray_dir

    def run(self) -> None:
        try:
            result = test_node(self.node, self.xray_dir)
            self.done.emit(self.node.id, self.node.name, result.elapsed_ms)
        except Exception as error:
            self.failed.emit(self.node.id, self.node.name, str(error))


class LogBridge(QObject):
    message = Signal(str)


class NodeDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, node: Node | None = None) -> None:
        super().__init__(parent)
        self.node = node
        self.setWindowTitle("编辑节点" if node else "新增节点")
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
        if node:
            self.name.setText(node.name)
            self.protocol.setText(node.protocol)
            self.address.setText(node.address)
            self.port.setValue(node.port)
            self.credential.setText(node.credential)
            self.security.setText(node.security)
            self.transport.setText(node.transport)
            self.server_name.setText(node.server_name)

    def value(self) -> Node:
        values = {
            "name": self.name.text().strip(),
            "protocol": self.protocol.text().strip().lower(),
            "address": self.address.text().strip(),
            "port": self.port.value(),
            "credential": self.credential.text().strip(),
            "security": self.security.text().strip().lower(),
            "transport": self.transport.text().strip().lower(),
            "server_name": self.server_name.text().strip(),
        }
        return replace(self.node, **values) if self.node else Node(**values)


class InboundDialog(QDialog):
    MODES: ClassVar = {
        "全局走代理": "global",
        "跳过 CN": "bypass_cn",
    }

    PROTOCOLS: ClassVar = {"SOCKS5": "socks", "HTTP": "http"}

    def __init__(
        self,
        config: AppConfig,
        parent: QWidget | None = None,
        inbound: Inbound | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.inbound = inbound
        self.setWindowTitle("编辑入站" if inbound else "新增入站")
        form = QFormLayout(self)
        self.form = form
        self.name = QLineEdit()
        self.listen = QComboBox()
        self.listen.setEditable(True)
        self.listen.addItems(["127.0.0.1", "0.0.0.0"])
        self.listen.setCurrentText("127.0.0.1")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(10808)
        self.protocol = QComboBox()
        for label, value in self.PROTOCOLS.items():
            self.protocol.addItem(label, value)
        self.auth_username = QLineEdit()
        self.auth_username.setPlaceholderText("留空表示不启用鉴权")
        self.auth_password = QLineEdit()
        self.auth_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.auth_password.setPlaceholderText("留空表示不启用鉴权")
        self.node = QComboBox()
        for node in config.nodes:
            self.node.addItem(node.name, node.id)
        self.outbound_mode = QComboBox()
        self.outbound_mode.addItem("单节点", "single")
        self.outbound_mode.addItem("轮询", "round_robin")
        self.round_robin_all = QCheckBox("全部")
        self.round_robin_nodes = QListWidget()
        self.round_robin_nodes.setMaximumHeight(130)
        for node in config.nodes:
            item = QListWidgetItem(node.name)
            item.setData(Qt.ItemDataRole.UserRole, node.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.round_robin_nodes.addItem(item)
        self.mode = QComboBox()
        for label, value in self.MODES.items():
            self.mode.addItem(label, value)
        self.skip_private = QCheckBox()
        self.skip_private.setChecked(True)
        for label, widget in (
            ("名称", self.name),
            ("入站协议", self.protocol),
            ("监听地址", self.listen),
            ("端口", self.port),
            ("鉴权用户名", self.auth_username),
            ("鉴权密码", self.auth_password),
            ("出口方式", self.outbound_mode),
            ("单节点", self.node),
            ("轮询节点", self.round_robin_all),
            ("", self.round_robin_nodes),
            ("路由模式", self.mode),
            ("跳过私有地址", self.skip_private),
        ):
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.outbound_mode.currentIndexChanged.connect(self._update_outbound_visibility)
        self.round_robin_all.toggled.connect(self._toggle_all_nodes)
        self.round_robin_nodes.itemChanged.connect(self._update_all_state)
        if inbound:
            self.name.setText(inbound.name)
            self.listen.setCurrentText(inbound.listen)
            self.port.setValue(inbound.port)
            self.auth_username.setText(inbound.auth_username)
            self.auth_password.setText(inbound.auth_password)
            self._select_data(self.protocol, inbound.protocol)
            self._select_data(self.node, inbound.node_id)
            self._select_data(
                self.outbound_mode, "round_robin" if inbound.round_robin else "single"
            )
            selected_ids = set(inbound.round_robin_node_ids)
            select_all = inbound.round_robin and not selected_ids
            for index in range(self.round_robin_nodes.count()):
                item = self.round_robin_nodes.item(index)
                if select_all or item.data(Qt.ItemDataRole.UserRole) in selected_ids:
                    item.setCheckState(Qt.CheckState.Checked)
            self._select_data(self.mode, inbound.route_mode)
            self.skip_private.setChecked(inbound.skip_private)
        self._update_all_state()
        self._update_outbound_visibility()

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _update_outbound_visibility(self) -> None:
        round_robin = self.outbound_mode.currentData() == "round_robin"
        self.node.setVisible(not round_robin)
        self.form.labelForField(self.node).setVisible(not round_robin)
        self.round_robin_all.setVisible(round_robin)
        self.form.labelForField(self.round_robin_all).setVisible(round_robin)
        self.round_robin_nodes.setVisible(round_robin)

    def _toggle_all_nodes(self, checked: bool) -> None:
        self.round_robin_nodes.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.round_robin_nodes.count()):
            self.round_robin_nodes.item(index).setCheckState(state)
        self.round_robin_nodes.blockSignals(False)

    def _update_all_state(self) -> None:
        count = self.round_robin_nodes.count()
        checked = sum(
            self.round_robin_nodes.item(index).checkState() == Qt.CheckState.Checked
            for index in range(count)
        )
        self.round_robin_all.blockSignals(True)
        self.round_robin_all.setChecked(count > 0 and checked == count)
        self.round_robin_all.blockSignals(False)

    def _selected_round_robin_nodes(self) -> list[str]:
        return [
            str(self.round_robin_nodes.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.round_robin_nodes.count())
            if self.round_robin_nodes.item(index).checkState() == Qt.CheckState.Checked
        ]

    def value(self) -> Inbound:
        node_id = self.node.currentData()
        if not node_id:
            raise ValueError("找不到指定的出口节点")
        round_robin = self.outbound_mode.currentData() == "round_robin"
        selected_ids = self._selected_round_robin_nodes() if round_robin else []
        if round_robin and len(selected_ids) < 2:
            raise ValueError("轮询出口至少选择两个节点")
        selected_node_id = selected_ids[0] if round_robin else str(node_id)
        values = {
            "name": self.name.text().strip(),
            "listen": self.listen.currentText().strip(),
            "port": self.port.value(),
            "node_id": selected_node_id,
            "route_mode": str(self.mode.currentData()),
            "protocol": str(self.protocol.currentData()),
            "auth_username": self.auth_username.text().strip(),
            "auth_password": self.auth_password.text(),
            "skip_private": self.skip_private.isChecked(),
            "round_robin": round_robin,
            "round_robin_node_ids": selected_ids,
        }
        return replace(self.inbound, **values) if self.inbound else Inbound(**values)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = JsonConfigStore()
        self.logger = configure_logging()
        self.config = self.store.load()
        legacy_xray_dir = str(default_data_dir() / "core")
        if not self.config.settings.xray_dir or self.config.settings.xray_dir == legacy_xray_dir:
            self.config.settings.xray_dir = "./"
        self.log_bridge = LogBridge()
        self.log_bridge.message.connect(self.append_log)
        self.manager = XrayProcessManager(self.log_bridge.message.emit)
        self.worker: UpdateWorker | None = None
        self.test_worker: NodeTestWorker | None = None
        self.test_queue: list[str] = []
        self.testing_all_nodes = False
        self.test_batch_success = 0
        self.test_batch_failed = 0
        self.node_results: dict[str, tuple[str, bool]] = {}
        self.closing_all = False
        self.setWindowTitle("Xray UI")
        self.resize(920, 620)
        self.setStyleSheet(
            "QTableWidget { selection-background-color: #2563eb; selection-color: white; }"
            "QTableWidget::item:hover { background: #dbeafe; color: #111827; }"
            "QPushButton:disabled { color: #9ca3af; background: #e5e7eb; }"
        )
        self._build_ui()
        attached = self.manager.attach(Path(self.config.settings.xray_dir))
        if attached:
            self._set_runtime_status(True)
        self._build_tray()
        self.refresh()
        self.audit("应用启动")
        if attached:
            self.audit(f"已关联后台 Xray 进程，PID {self.manager.pid}")
        QTimer.singleShot(0, self._after_startup)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        self.status = QLabel()
        self._set_runtime_status(False)
        self.start_button = QPushButton("启动")
        self.stop_button = QPushButton("停止")
        self.update_button = QPushButton("下载/更新 Xray")
        self.exit_ui_button = QPushButton("退出 UI")
        for button in (
            self.start_button,
            self.stop_button,
            self.update_button,
            self.exit_ui_button,
        ):
            button.setFixedHeight(26)
            button.setMinimumWidth(82)
        self.update_button.setMinimumWidth(112)
        self.start_button.clicked.connect(self.start_xray)
        self.stop_button.clicked.connect(self.stop_xray)
        self.update_button.clicked.connect(self.update_xray)
        self.exit_ui_button.clicked.connect(self._exit_app)

        tabs = QTabWidget()
        self.node_table = QTableWidget(0, 5)
        self.node_table.setHorizontalHeaderLabels(["名称", "协议", "地址", "端口", "测试结果"])
        self.inbound_table = QTableWidget(0, 7)
        self.inbound_table.setHorizontalHeaderLabels(
            ["名称", "协议", "监听", "端口", "鉴权", "出口", "路由"]
        )
        tabs.addTab(
            self._table_page(
                self.node_table,
                self.add_node,
                self.remove_node,
                (
                    ("import", "从链接导入", self.import_node),
                    ("copy", "复制分享链接", self.copy_node_link),
                    ("test", "全部测试", self.test_all_nodes),
                    ("edit", "编辑", self.edit_node),
                ),
            ),
            "节点",
        )
        tabs.addTab(
            self._table_page(
                self.inbound_table,
                self.add_inbound,
                self.remove_inbound,
                (("edit", "编辑", self.edit_inbound),),
            ),
            "入站",
        )
        tabs.addTab(self._settings_page(), "设置")

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(4)
        corner_layout.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignVCenter)
        corner_layout.addWidget(self.update_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        corner_layout.addWidget(self.start_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        corner_layout.addWidget(self.stop_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        corner_layout.addWidget(self.exit_ui_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("运行日志"))
        log_header.addStretch()
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.clear_logs)
        log_header.addWidget(clear_button)
        log_layout.addLayout(log_header)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(500)
        log_layout.addWidget(self.logs)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(tabs)
        splitter.addWidget(log_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.node_table.itemSelectionChanged.connect(self.update_action_states)
        self.inbound_table.itemSelectionChanged.connect(self.update_action_states)
        self.node_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.node_table.customContextMenuRequested.connect(self._show_node_context_menu)
        self.node_table.itemDoubleClicked.connect(lambda _: self.edit_node())
        self.inbound_table.itemDoubleClicked.connect(lambda _: self.edit_inbound())
        self.update_action_states()

    def _table_page(self, table, add, remove, extra_actions=()) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(9, 18, 9, 9)
        layout.addWidget(table)
        row = QHBoxLayout()
        add_button, remove_button = QPushButton("新增"), QPushButton("删除")
        add_button.clicked.connect(add)
        remove_button.clicked.connect(remove)
        row.addStretch()
        buttons = {"add": add_button, "remove": remove_button}
        for key, text, action in extra_actions:
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
            buttons[key] = button
        row.addWidget(add_button)
        row.addWidget(remove_button)
        layout.addLayout(row)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        if table is self.node_table:
            for column, width in enumerate((140, 100, 200, 90, 200)):
                table.setColumnWidth(column, width)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            self.node_buttons = buttons
        else:
            for column, width in enumerate((140, 100, 120, 80, 100, 220, 170)):
                table.setColumnWidth(column, width)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            self.inbound_buttons = buttons
        return page

    def _settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        columns = QHBoxLayout(page)
        basic_group = QGroupBox("基础设置")
        basic_form = QFormLayout(basic_group)
        global_group = QGroupBox("全局配置")
        global_layout = QVBoxLayout(global_group)
        global_form = QFormLayout()
        self.xray_dir = QLineEdit(self.config.settings.xray_dir)
        self.ghproxy = QLineEdit(self.config.settings.ghproxy)
        self.ghproxy.setPlaceholderText("例如 https://gh-proxy.com")
        self.dns_server = QLineEdit(self.config.settings.dns_server)
        self.dns_server.setPlaceholderText("留空表示不配置 DNS")
        self.enable_ipv6 = QCheckBox()
        self.enable_ipv6.setChecked(self.config.settings.enable_ipv6)
        self.enable_xray_log = QCheckBox()
        self.enable_xray_log.setChecked(self.config.settings.enable_xray_log)
        self.xray_log_level = QComboBox()
        for label, value in (
            ("调试", "debug"),
            ("信息", "info"),
            ("警告", "warning"),
            ("错误", "error"),
        ):
            self.xray_log_level.addItem(label, value)
        log_level_index = self.xray_log_level.findData(self.config.settings.xray_log_level)
        if log_level_index >= 0:
            self.xray_log_level.setCurrentIndex(log_level_index)
        self.xray_log_level.setEnabled(self.enable_xray_log.isChecked())
        self.enable_xray_log.toggled.connect(self.xray_log_level.setEnabled)
        self.xray_log_file = QLineEdit(self.config.settings.xray_log_file)
        self.xray_log_file.setPlaceholderText("例如 ./log/xray.log，留空表示输出到控制台")
        self.xray_log_file.setEnabled(self.enable_xray_log.isChecked())
        self.enable_xray_log.toggled.connect(self.xray_log_file.setEnabled)
        self.use_ghproxy = QCheckBox()
        self.use_ghproxy.setChecked(self.config.settings.use_ghproxy)
        self.auto_update = QCheckBox()
        self.auto_update.setChecked(self.config.settings.auto_update)
        self.auto_start_xray = QCheckBox()
        self.auto_start_xray.setChecked(self.config.settings.auto_start_xray)
        self.start_with_windows = QCheckBox()
        self.start_with_windows.setChecked(self.config.settings.start_with_windows)
        self.proxy_domains = QTextEdit()
        self.proxy_domains.setMinimumHeight(100)
        self.proxy_domains.setPlainText("\n".join(self.config.proxy_domains))
        self.proxy_domains.setPlaceholderText(
            "每行一个强制走代理的域名，例如 example.com 或 *.example.com"
        )
        self.direct_domains = QTextEdit()
        self.direct_domains.setMinimumHeight(100)
        self.direct_domains.setPlainText("\n".join(self.config.direct_domains))
        self.direct_domains.setPlaceholderText(
            "每行一个强制直连的域名，例如 example.cn 或 *.example.cn"
        )
        save = QPushButton("保存设置")
        save.clicked.connect(self.save_settings)
        basic_form.addRow("Xray 目录", self.xray_dir)
        basic_form.addRow("ghproxy", self.ghproxy)
        basic_form.addRow("可信 DNS", self.dns_server)
        basic_form.addRow("启用 IPv6", self.enable_ipv6)
        basic_form.addRow("启用 Xray 日志", self.enable_xray_log)
        basic_form.addRow("Xray 日志等级", self.xray_log_level)
        basic_form.addRow("Xray 日志文件", self.xray_log_file)
        basic_form.addRow("使用 ghproxy 下载", self.use_ghproxy)
        basic_form.addRow("启动时检查更新", self.auto_update)
        basic_form.addRow("启动应用后运行 Xray", self.auto_start_xray)
        basic_form.addRow("开机启动", self.start_with_windows)

        global_form.addRow("全局代理域名", self.proxy_domains)
        global_form.addRow("全局直连域名", self.direct_domains)
        global_layout.addLayout(global_form)
        global_layout.addStretch()
        global_layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)

        columns.addWidget(basic_group, 1)
        columns.addWidget(global_group, 1)
        scroll.setWidget(page)
        return scroll

    def _build_tray(self) -> None:
        icon_path = resource_path("resources/xray-ui.ico")
        icon = (
            QIcon(str(icon_path))
            if icon_path.exists()
            else self.style().standardIcon(QStyle.SP_ComputerIcon)
        )
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
        exit_ui_action = QAction("退出 UI（保留 Xray）", self)
        exit_all_action = QAction("全部退出", self)
        show_action.triggered.connect(self._show_window)
        start_action.triggered.connect(self.start_xray)
        stop_action.triggered.connect(self.stop_xray)
        exit_ui_action.triggered.connect(self._exit_app)
        exit_all_action.triggered.connect(self._exit_all)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(start_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(exit_ui_action)
        menu.addAction(exit_all_action)
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
        if self.config.settings.auto_start_xray and not self.manager.running:
            self.audit("自动启动 Xray")
            self.start_xray()

    def refresh(self) -> None:
        self.node_table.setRowCount(len(self.config.nodes))
        for row, node in enumerate(self.config.nodes):
            result_text, success = self.node_results.get(node.id, ("未测试", True))
            for column, value in enumerate(
                (node.name, node.protocol, node.address, str(node.port), result_text)
            ):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 4 and result_text != "未测试":
                    cell.setForeground(QColor("#15803d" if success else "#b91c1c"))
                self.node_table.setItem(row, column, cell)
        names = {node.id: node.name for node in self.config.nodes}
        route_names = {
            "global": "全局走代理",
            "bypass_cn": "跳过 CN",
        }
        protocol_names = {"http": "HTTP", "socks": "SOCKS5"}
        self.inbound_table.setRowCount(len(self.config.inbounds))
        for row, item in enumerate(self.config.inbounds):
            route_label = route_names.get(item.route_mode, item.route_mode)
            if item.skip_private:
                route_label += " / 私有直连"
            selected_count = len(item.round_robin_node_ids)
            all_nodes = not item.round_robin_node_ids or selected_count == len(self.config.nodes)
            outbound_label = (
                "轮询：全部"
                if item.round_robin and all_nodes
                else f"轮询：{selected_count} 个节点"
                if item.round_robin
                else names.get(item.node_id, "无效")
            )
            values = (
                item.name,
                protocol_names.get(item.protocol, item.protocol),
                item.listen,
                str(item.port),
                "已启用" if item.auth_username else "无",
                outbound_label,
                route_label,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.inbound_table.setItem(row, column, cell)
        self.update_action_states()

    def update_action_states(self) -> None:
        node_selected = 0 <= self.node_table.currentRow() < len(self.config.nodes)
        inbound_selected = 0 <= self.inbound_table.currentRow() < len(self.config.inbounds)
        testing = bool(self.test_worker and self.test_worker.isRunning())
        busy = testing
        for key in ("copy", "edit", "remove"):
            self.node_buttons[key].setEnabled(node_selected and not busy)
        self.node_buttons["test"].setEnabled(bool(self.config.nodes) and not busy)
        self.node_buttons["add"].setEnabled(not busy)
        self.node_buttons["import"].setEnabled(not busy)
        self.inbound_buttons["add"].setEnabled(bool(self.config.nodes))
        self.inbound_buttons["edit"].setEnabled(inbound_selected)
        self.inbound_buttons["remove"].setEnabled(inbound_selected)
        self.start_button.setVisible(not self.manager.running)
        self.stop_button.setVisible(self.manager.running)
        self.stop_button.setEnabled(self.manager.running)
        self.update_button.setEnabled(not bool(self.worker and self.worker.isRunning()))

    def _set_runtime_status(self, running: bool) -> None:
        self.status.setFixedWidth(88)
        self.status.setFixedHeight(26)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if running:
            self.status.setText("运行中")
            foreground, background = "#166534", "#dcfce7"
        else:
            self.status.setText("已停止")
            foreground, background = "#991b1b", "#fee2e2"
        self.status.setStyleSheet(
            f"color: {foreground}; background: {background}; font-weight: 600; "
            "padding: 1px 8px; border-radius: 4px;"
        )

    def add_node(self) -> None:
        dialog = NodeDialog(self)
        if dialog.exec():
            self.config.nodes.append(dialog.value())
            self._save_refresh()
            self.audit(f"新增节点：{self.config.nodes[-1].name}")

    def edit_node(self) -> None:
        row = self.node_table.currentRow()
        if row < 0:
            self.error("请先选择节点")
            return
        original = self.config.nodes[row]
        dialog = NodeDialog(self, original)
        if dialog.exec():
            self.config.nodes[row] = dialog.value()
            self._save_refresh()
            self.audit(f"编辑节点：{self.config.nodes[row].name}")

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
        self.testing_all_nodes = False
        self.test_queue.clear()
        self._start_node_test(node)

    def test_all_nodes(self) -> None:
        if not self.config.nodes:
            self.error("暂无可测试的节点")
            return
        if self.test_worker and self.test_worker.isRunning():
            self.error("已有节点正在测试")
            return
        self.testing_all_nodes = True
        self.test_batch_success = 0
        self.test_batch_failed = 0
        self.test_queue = [node.id for node in self.config.nodes]
        for node in self.config.nodes:
            self.node_results[node.id] = ("等待测试", True)
        self.audit(f"开始测试全部节点，共 {len(self.test_queue)} 个")
        self._start_next_node_test()

    def _start_next_node_test(self) -> None:
        while self.test_queue:
            node_id = self.test_queue.pop(0)
            node = next((item for item in self.config.nodes if item.id == node_id), None)
            if node:
                self._start_node_test(node)
                return
        self.testing_all_nodes = False
        self.refresh()
        message = (
            f"全部节点测试完成：成功 {self.test_batch_success} 个，"
            f"失败 {self.test_batch_failed} 个"
        )
        self.audit(message)
        QMessageBox.information(self, "节点测试", message)

    def _start_node_test(self, node: Node) -> None:
        self.node_results[node.id] = ("测试中…", True)
        self.refresh()
        self.audit(f"开始测试节点：{node.name}")
        self.test_worker = NodeTestWorker(node, Path(self.config.settings.xray_dir))
        self.test_worker.done.connect(self._node_test_done)
        self.test_worker.failed.connect(self._node_test_failed)
        self.test_worker.finished.connect(self._node_test_finished)
        self.test_worker.start()
        self.update_action_states()

    def _node_test_done(self, node_id: str, name: str, elapsed_ms: int) -> None:
        self.node_results[node_id] = (f"{elapsed_ms} ms", True)
        self.refresh()
        message = f"节点 {name} 测试成功：{elapsed_ms} ms"
        self.audit(message)
        if self.testing_all_nodes:
            self.test_batch_success += 1
        else:
            QMessageBox.information(self, "节点测试", message)

    def _node_test_failed(self, node_id: str, name: str, reason: str) -> None:
        self.node_results[node_id] = ("失败", False)
        self.refresh()
        message = f"节点 {name} 测试失败：{reason}"
        if self.testing_all_nodes:
            self.test_batch_failed += 1
            self.audit(message)
        else:
            self.error(message)

    def _node_test_finished(self) -> None:
        self.test_worker = None
        self.update_action_states()
        if self.testing_all_nodes:
            QTimer.singleShot(0, self._start_next_node_test)

    def _show_node_context_menu(self, position) -> None:
        index = self.node_table.indexAt(position)
        if not index.isValid():
            return
        self.node_table.selectRow(index.row())
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        test_action = menu.addAction("测试此节点")
        test_action.setEnabled(not bool(self.test_worker and self.test_worker.isRunning()))
        selected = menu.exec(self.node_table.viewport().mapToGlobal(position))
        if selected is test_action:
            self.test_selected_node()

    def remove_node(self) -> None:
        row = self.node_table.currentRow()
        if row >= 0:
            node_id = self.config.nodes[row].id
            if any(
                item.node_id == node_id
                or (
                    item.round_robin
                    and (not item.round_robin_node_ids or node_id in item.round_robin_node_ids)
                )
                for item in self.config.inbounds
            ):
                self.error("该节点仍被入站使用")
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
                self.audit(f"新增入站：{self.config.inbounds[-1].name}")
            except ValueError as error:
                self.error(str(error))

    def edit_inbound(self) -> None:
        row = self.inbound_table.currentRow()
        if row < 0:
            self.error("请先选择入站")
            return
        dialog = InboundDialog(self.config, self, self.config.inbounds[row])
        if dialog.exec():
            try:
                self.config.inbounds[row] = dialog.value()
                self._save_refresh()
                self.audit(f"编辑入站：{self.config.inbounds[row].name}")
            except ValueError as error:
                self.error(str(error))

    def remove_inbound(self) -> None:
        row = self.inbound_table.currentRow()
        if row >= 0:
            self.config.inbounds.pop(row)
            self._save_refresh()
            self.audit("删除入站")

    def save_settings(self) -> None:
        self.config.settings.xray_dir = self.xray_dir.text().strip()
        self.config.settings.ghproxy = self.ghproxy.text().strip()
        self.config.settings.dns_server = self.dns_server.text().strip()
        self.config.settings.enable_ipv6 = self.enable_ipv6.isChecked()
        self.config.settings.enable_xray_log = self.enable_xray_log.isChecked()
        self.config.settings.xray_log_level = str(self.xray_log_level.currentData())
        self.config.settings.xray_log_file = self.xray_log_file.text().strip()
        self.config.settings.use_ghproxy = self.use_ghproxy.isChecked()
        self.config.settings.auto_update = self.auto_update.isChecked()
        self.config.settings.auto_start_xray = self.auto_start_xray.isChecked()
        self.config.settings.start_with_windows = self.start_with_windows.isChecked()
        self.config.proxy_domains = [
            line.strip() for line in self.proxy_domains.toPlainText().splitlines() if line.strip()
        ]
        self.config.direct_domains = [
            line.strip() for line in self.direct_domains.toPlainText().splitlines() if line.strip()
        ]
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
            self._set_runtime_status(True)
            self.audit("启动 Xray")
            self.update_action_states()
        except Exception as error:
            self.error(str(error))

    def stop_xray(self) -> None:
        self.manager.stop()
        self._set_runtime_status(False)
        self.audit("停止 Xray")
        self.update_action_states()

    def update_xray(self) -> None:
        if self.worker and self.worker.isRunning():
            self.audit("忽略重复的 Xray 更新请求")
            return
        self.audit("检查并更新 Xray")
        proxy = self.ghproxy.text().strip() if self.use_ghproxy.isChecked() else ""
        updater = XrayUpdater(Path(self.xray_dir.text().strip()), proxy)
        self.worker = UpdateWorker(updater)
        self.worker.status.connect(self.audit)
        self.worker.progress.connect(lambda value: self.audit(f"Xray-core 下载进度：{value}%"))
        self.worker.done.connect(self._update_done)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.update_action_states)
        self.worker.start()
        self.update_action_states()

    def _save_refresh(self) -> None:
        try:
            self.store.save(self.config)
            self.refresh()
        except ValueError as error:
            self.error(str(error))

    def append_log(self, text: str) -> None:
        self.logs.append(text)
        self.logger.info("[XRAY] %s", text)

    def clear_logs(self) -> None:
        self.logs.clear()
        self.logger.info("[UI] 清空界面日志")

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
        if not self.closing_all:
            self.audit("退出 UI，Xray 保持后台运行")
        event.accept()

    def _show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.audit("从系统托盘显示窗口")

    def _exit_app(self) -> None:
        self.close()

    def _exit_all(self) -> None:
        self.closing_all = True
        self.manager.stop()
        self._set_runtime_status(False)
        self.audit("全部退出：已停止 Xray 并关闭 UI")
        self.close()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
