# codex-note-reminder

## 中文

macOS 上的 Codex CLI 通知：当运行 Codex 的 iTerm2 会话不在前台时，通过 Bark 提醒本轮回复完成、需要授权、需要输入或选择。通知仅含项目目录名和简短状态，不发送对话内容。手动测试不受前台限制。

**依赖：** macOS、iTerm2、Codex CLI、Bark App、系统自带的 `/usr/bin/python3`（3.9 或更新版本）和 `/usr/bin/curl`。安装不需要第三方 Python 包。

```sh
/usr/bin/python3 install.py
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --setup-key
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --test
```

`--setup-key` 会隐藏输入，将 Bark 设备密钥保存为用户私有的 `0600` 文件。默认直连 `api.day.app`；如需代理，安装时加 `--proxy http://127.0.0.1:7890`，测试时也加同一选项。代理 URL 请勿包含账号密码。

安装后在 Codex CLI 输入 `/hooks`，检查并信任新增 hooks；更新 hook 命令后需重新信任。修改 `config.toml` 或 `hooks.json` 前，安装器会在 `CODEX_HOME/backups/codex-note-reminder/` 保存备份。若已有其他 `notify`，安装器会报错，需先自行处理冲突。

卸载：`/usr/bin/python3 install.py --uninstall`。卸载保留 Bark 密钥，可手动删除 `${CODEX_HOME:-$HOME/.codex}/bark_device_key`。首版只支持 iTerm2；授权和输入提醒依赖 Codex CLI 对相应 hook 的支持与信任。

## English

For Codex CLI on macOS, Bark alerts when the originating iTerm2 session is in the background: turn complete, permission needed, or input/choice needed. Notifications contain only the project folder name and a short status. Manual `--test` always sends.

**Requires:** macOS, iTerm2, Codex CLI, Bark, `/usr/bin/python3` (3.9+) and `/usr/bin/curl`. No third-party Python packages.

```sh
/usr/bin/python3 install.py
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --setup-key
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --test
```

`--setup-key` prompts without echo and stores the Bark device key in a private `0600` file. Bark is contacted directly by default. For a proxy, add `--proxy http://127.0.0.1:7890` to installation and testing; do not put credentials in the proxy URL.

In Codex CLI, open `/hooks`, review and trust the new hooks. Changed hook definitions need renewed trust. The installer backs up configuration under `CODEX_HOME/backups/codex-note-reminder/` and rejects an existing, unrelated `notify` command.

Uninstall with `/usr/bin/python3 install.py --uninstall`. The Bark key is retained; delete `${CODEX_HOME:-$HOME/.codex}/bark_device_key` manually if desired. This release supports iTerm2 only. Permission and input alerts depend on the relevant Codex CLI hooks being supported and trusted.
