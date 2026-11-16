# Xray UI

面向 Windows 的轻量 Xray 客户端管理器。应用使用表单维护配置，用户无需编辑 Xray JSON。

## 当前功能

- 支持 HTTP、SOCKS5、单端口 Mixed（HTTP + SOCKS5）三种入站
- 每个 Mixed 入站独立绑定出口节点
- 每个入站可选全局或跳过 CN，另有默认开启的“跳过私有地址”开关
- 全局直连域名规则独立配置，对所有入站生效
- VLESS、VMess、Trojan、Shadowsocks、SOCKS、HTTP 出口基础配置
- 配置使用 `%LOCALAPPDATA%\xray-ui\config.json` 保存
- 自动下载/更新官方 Xray-core，支持 ghproxy URL 前缀
- 从 `vless://`、`vmess://`、`trojan://`、`ss://`、`socks://`、`http://` 分享链接导入节点
- 将节点重新生成分享链接并复制到剪贴板
- 保留 VLESS Encryption、VMess 加密、TLS/REALITY、ALPN、WebSocket、gRPC、XHTTP 等分享参数
- 通过临时 Xray HTTP 入站实际测试节点连通性和响应耗时
- 支持按顺序轮询全部节点，并在表格显示延迟或失败状态
- 启动前执行 Xray 配置校验，捕获运行日志，停止时清理进程树
- 日志固定显示在主窗口底部，最多保留最新 500 行并支持清空
- 节点和入站均支持编辑
- 不修改 Windows 系统代理

## 开发运行

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\xray-ui.exe
```

Mixed 由应用内的 TCP 协议分流器实现，Xray-core 内部使用两个仅监听 `127.0.0.1` 的随机端口。

