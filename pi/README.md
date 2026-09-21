# Pi Bark Reminder

在 Mac 的 iTerm2 中运行 Pi 时，只要当前 iTerm2 会话不在前台，Pi 完成本轮工作或弹出阻塞式输入框时，就通过 Bark 向手机发送通知。若已为 Bark 开启 Apple Watch 通知，提醒也可显示在手表上。

| Pi 状态 | 通知内容 |
| --- | --- |
| 自动重试、压缩和排队的后续工作全部结束 | `项目名：本轮回复已完成` |
| 扩展正在等待选择、确认、文本输入或自定义交互 | `项目名：需要输入或选择` |

通知只包含项目文件夹名和简短状态，不包含对话内容。当前 iTerm2 会话在前台时不发送事件通知；手动测试始终发送。

## 环境要求

- macOS、iTerm2、Pi 0.86.1 或更新版本。
- 系统自带的 `/usr/bin/python3` 和 `/usr/bin/curl`。
- 手机已安装 Bark，并能从 Bark App 中复制设备密钥。

## 安装到 Pi

在本项目目录运行：

```sh
pi install "$PWD"
```

这是 Pi 原生扩展，不需要特殊启动器；安装后照常运行 `pi` 即可。Pi 本身支持热重载，但首次安装后建议重新启动当前 Pi 会话。

## 配置 Bark

首次使用时录入设备密钥。输入不会回显，密钥存放在 `~/.pi/agent/bark_device_key`，文件权限为 `0600`：

```sh
/usr/bin/python3 pi/bark_notify.py --setup-key
```

如果此前已经使用本项目的 Codex 版本，可直接安全迁移原有密钥，不会在终端输出密钥内容：

```sh
/usr/bin/python3 pi/bark_notify.py --migrate-codex-key
```

发送测试通知：

```sh
/usr/bin/python3 pi/bark_notify.py --test
```

测试通知不受 iTerm2 前后台状态限制。实际使用时，在 Pi 中发出请求后切换到其他窗口或应用；Pi 完成后应收到 Bark 通知。切回原 iTerm2 会话后，事件通知应被抑制。

## 可选代理

需要代理访问 Bark 时，可以保存一个不含账号密码的代理 URL：

```sh
/usr/bin/python3 pi/bark_notify.py --setup-proxy http://127.0.0.1:7890
```

清除代理配置：

```sh
/usr/bin/python3 pi/bark_notify.py --clear-proxy
```

## 卸载

```sh
pi remove "$PWD"
```

Pi 只会移除扩展登记，不会删除 Bark 密钥和代理配置。如不再使用，可手动删除：

```sh
rm ~/.pi/agent/bark_device_key ~/.pi/agent/bark-reminder.json
```

## 工作原理

扩展使用 Pi 的 `agent_settled` 事件判断整轮工作真正完成，并使用 `ui_prompt_start` 识别阻塞式用户输入。事件触发后，辅助程序通过 AppleScript 比较启动 Pi 的 iTerm2 会话与当前可见会话；仅在二者不同时调用 Bark API。

说明：Pi 的核心工具默认不会在执行前弹出授权框。若其他扩展通过 `ctx.ui.confirm()` 等接口请求确认，这类等待会归入“需要输入或选择”。
