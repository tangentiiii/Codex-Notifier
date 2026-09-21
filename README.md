# Codex / Pi Bark Reminder

在 Mac 的 iTerm2 中运行 Codex CLI 或 Pi 时，只要对应的 iTerm2 会话不在前台，智能体完成回复或等待用户输入时，就通过 Bark 向手机发送通知。若已为 Bark 开启 Apple Watch 通知，提醒也可显示在手表上。

仓库同时保留两套独立实现：

```text
.
├── codex/                  # Codex CLI hooks、通知程序与审批启动器
├── pi/                     # Pi 原生扩展与通知程序
├── tests/                  # 两套实现各自的测试
├── package.json            # Pi 包入口
└── README.md               # 总览
```

两套实现互不覆盖：Codex 使用 `${CODEX_HOME:-~/.codex}`，Pi 使用 `${PI_CODING_AGENT_DIR:-~/.pi/agent}`。Bark 密钥分别存放，通知内容只包含项目文件夹名和简短状态，不包含对话正文。

## Pi

Pi 通过原生扩展事件监听真正完成和阻塞式输入，无需特殊启动器。

```sh
pi install "$PWD"
/usr/bin/python3 pi/bark_notify.py --setup-key
/usr/bin/python3 pi/bark_notify.py --test
```

如果 Codex 版本已经保存过 Bark 密钥，可以无回显地复制到 Pi：

```sh
/usr/bin/python3 pi/bark_notify.py --migrate-codex-key
```

完整说明见 [pi/README.md](pi/README.md)。

## Codex CLI

Codex 版本保留原有通知 hook 和审批请求启动器。安装时从 `codex/` 目录运行：

```sh
cd codex
/usr/bin/python3 install.py
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --setup-key
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --test
```

需要准确的人工授权提醒时，通过安装后的启动器运行 Codex：

```sh
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder_cli.py"
```

完整说明见 [codex/README.md](codex/README.md)。

## 测试

```sh
npm test
```

测试覆盖两套配置目录、事件路由、iTerm2 前后台判断、Bark 请求、代理设置、Pi 包清单，以及 Codex 审批代理。
