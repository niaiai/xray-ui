# Xray UI

面向 Windows 的轻量 Xray 客户端管理器。应用使用表单维护配置，用户无需编辑 Xray JSON。

## 当前功能

- 多个单端口 Mixed 入站（同一端口同时接受 SOCKS4/5 与 HTTP）
- 每个 Mixed 入站独立绑定出口节点
- 全局、跳过 CN、自定义域名直连三种路由模式
- VLESS、VMess、Trojan、Shadowsocks、SOCKS、HTTP 出口基础配置
- 配置使用 `%LOCALAPPDATA%\xray-ui\config.json` 保存
- 自动下载/更新官方 Xray-core，支持 ghproxy URL 前缀
- 从 `vless://`、`vmess://`、`trojan://`、`ss://`、`socks://`、`http://` 分享链接导入节点
- 将节点重新生成分享链接并复制到剪贴板
- 启动前执行 Xray 配置校验，捕获运行日志，停止时清理进程树
- UI 操作和 Xray 输出写入 `%LOCALAPPDATA%\xray-ui\logs\xray-ui.log`，自动滚动保留 5 份
- 不修改 Windows 系统代理

## 开发运行

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\xray-ui.exe
```

Mixed 由应用内的 TCP 协议分流器实现，Xray-core 内部使用两个仅监听 `127.0.0.1` 的随机端口。

