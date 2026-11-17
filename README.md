# Xray UI

面向 Windows 的轻量 Xray 客户端管理器。应用使用表单维护配置，用户无需编辑 Xray JSON。

## 当前功能

- 支持 HTTP、SOCKS5 两种入站
- HTTP 与 SOCKS5 入站支持可选的用户名、密码鉴权
- 每个入站可绑定单个出口节点或轮询全部节点
- 每个入站可选全局或跳过 CN，另有默认开启的“跳过私有地址”开关
- 全局代理域名规则优先于跳过 CN 和私有直连，并按各入站出口代理
- 通过流量嗅探恢复目标域名，并使用可配置的可信 DoH 防止本地 DNS 污染
- VLESS、VMess、Trojan、Shadowsocks、SOCKS、HTTP 出口基础配置
- 应用配置保存为程序同目录的 `config.json`
- Xray 运行配置保存为程序同目录的 `xray-runtime.json`
- 自动下载/更新官方 Xray-core，支持 ghproxy URL 前缀
- 从 `vless://`、`vmess://`、`trojan://`、`ss://`、`socks://`、`http://` 分享链接导入节点
- 将节点重新生成分享链接并复制到剪贴板
- 保留 VLESS Encryption、VMess 加密、TLS/REALITY、ALPN、WebSocket、gRPC、XHTTP 等分享参数
- 通过临时 Xray HTTP 入站实际测试节点连通性和响应耗时
- 入站出口可选择单节点，或勾选部分/全部节点进行 Xray Round Robin 轮询
- 默认从程序当前目录管理 `xray.exe`、`geoip.dat` 和 `geosite.dat`
- 默认启用已验证可用的 `https://gh-proxy.com`，可在设置中取消勾选
- 启动前执行 Xray 配置校验，捕获运行日志，停止时清理进程树
- UI 可独立退出并保留 Xray 后台运行，再次打开时自动关联原有进程
- 托盘菜单支持停止 Xray 并全部退出
- 日志固定显示在主窗口底部，最多保留最新 500 行并支持清空
- 节点和入站均支持编辑
- 不修改 Windows 系统代理

## Windows 打包

```powershell
.\scripts\build.ps1
```

输出为 `dist\XrayUI.exe`，使用 Windows GUI 子系统，不显示控制台黑框。

## 开发运行

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\xray-ui.exe
```

