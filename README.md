# Codex Note Reminder

[简体中文](#简体中文) · [English](#english)

## 简体中文

在 Mac 的 iTerm2 中运行 Codex CLI 时，**只要该 iTerm2 会话不在前台**，Codex 有新进展便可通过 Bark 向手机发送通知；如果已为 Bark 开启 Apple Watch 通知，提醒也可显示在手表上。你可以离开电脑，等手机或手表提醒后再回来处理。

| 何时提醒 | 手机上的简短状态 |
| --- | --- |
| Codex 完成本轮回复 | 本轮回复已完成 |
| Codex 等待授权 | 需要授权 |
| Codex 等待输入或选择 | 需要输入或选择 |

通知只包含项目文件夹名和上述状态，不包含对话内容。当前 iTerm2 会话在前台时不发送事件通知；手动 `--test` 始终发送。首版支持 **macOS + iTerm2 + Codex CLI + Bark**。

### 准备

- Mac 上已安装 iTerm2 和 Codex CLI；可运行系统自带的 `/usr/bin/python3`（3.9 或更新版本）及 `/usr/bin/curl`。
- 手机上已安装并启用 Bark，能在 Bark App 中找到并复制设备密钥。
- 如需在 Apple Watch 上看提醒，请在 iPhone 的 **Watch App → 我的手表 → 通知** 中允许 Bark 通知，并检查 iPhone 的 Bark 通知权限。[Apple 说明](https://support.apple.com/en-gb/108274)指出，通知通常会根据 iPhone 和手表的使用状态显示在其中一台设备上。

### 配置步骤

在本项目目录中按顺序操作：

1. **安装通知程序。** 安装器会读取 `CODEX_HOME`；未设置时使用 `~/.codex`。

   ```sh
   /usr/bin/python3 install.py
   ```

   安装器将程序放入 Codex 用户目录，并合并 `notify` 与两个 hooks。它会先备份现有配置；若检测到其他 `notify` 命令，则报错并保留原配置，需要先自行处理冲突。

2. **录入 Bark 设备密钥。** 从手机上的 Bark App 复制密钥，运行下面的命令，按提示粘贴并回车。输入过程不会回显；密钥保存在本机私有文件中，不写入仓库。

   ```sh
   /usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --setup-key
   ```

3. **让 Codex 信任 hooks。** 重新打开 Codex CLI，在其中输入 `/hooks`，检查新增的 `PermissionRequest` 和 `PreToolUse` 命令，然后信任它们。以后若更新了 hook 命令，需要再次检查并信任。`notify` 和 hooks 配合提供上述三类提醒。

4. **发送测试通知。** 这一步不受 iTerm2 前后台限制。在手机上确认收到 Bark 推送；如要在手表上接收，也检查手表的通知设置。

   ```sh
   /usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --test
   ```

5. **验证实际使用。** 在 iTerm2 中启动 Codex CLI，发出一个请求后切到其他窗口或应用。回复完成时应收到通知；切回该 iTerm2 会话后，事件通知应被抑制。授权及输入或选择提醒也需要在实际触发相应操作时检查。

### 可选：使用代理

默认直连 Bark。若当前网络需要代理，安装和测试时分别指定同一个代理地址：

```sh
/usr/bin/python3 install.py --proxy http://127.0.0.1:7890
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --test --proxy http://127.0.0.1:7890
```

代理 URL 不要包含账号密码。重复运行安装命令可以更新程序和代理配置。

### 卸载与数据

```sh
/usr/bin/python3 install.py --uninstall
```

安装器会移除自己添加的配置和程序，保留 Bark 密钥。若不再使用，请手动删除 `${CODEX_HOME:-$HOME/.codex}/bark_device_key`。配置备份位于 `${CODEX_HOME:-$HOME/.codex}/backups/codex-note-reminder/`。

---

## English

When Codex CLI runs in iTerm2 on your Mac, **Bark can notify your phone whenever that iTerm2 session is in the background**. With Bark notifications enabled for Apple Watch, the alert can also appear on your watch. Step away from your Mac and return when Codex needs you.

| Event | Current notification text |
| --- | --- |
| Codex finishes a turn | 本轮回复已完成 (turn complete) |
| Codex needs permission | 需要授权 (permission needed) |
| Codex needs input or a choice | 需要输入或选择 (input or choice needed) |

The actual notification contains only the project folder name and a short status; it never includes conversation text. Event alerts are suppressed while the originating iTerm2 session is in front. A manual `--test` always sends. This release supports **macOS + iTerm2 + Codex CLI + Bark**.

### Before you start

- Install iTerm2 and Codex CLI on your Mac. The system `/usr/bin/python3` (3.9+) and `/usr/bin/curl` must be available.
- Install Bark on your phone, enable its notifications, and locate your device key in the Bark app.
- For Apple Watch alerts, allow Bark notifications in **Watch app → My Watch → Notifications** and check Bark's iPhone notification permission. [Apple explains](https://support.apple.com/en-gb/108274) that alerts normally appear on either the iPhone or Apple Watch according to their current state.

### Setup, step by step

Run these commands from this project directory:

1. **Install the notifier.** The installer uses `CODEX_HOME` if set, or `~/.codex` otherwise.

   ```sh
   /usr/bin/python3 install.py
   ```

   It installs the program into your user Codex directory and merges `notify` with two hooks. Existing configuration is backed up first. If another `notify` command is present, installation stops without replacing it; resolve that conflict before retrying.

2. **Enter your Bark device key.** Copy it from the Bark app on your phone, run the command below, then paste it at the hidden prompt and press Return. The key is stored in a private local file, outside this repository.

   ```sh
   /usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --setup-key
   ```

3. **Trust the hooks in Codex.** Restart Codex CLI and enter `/hooks`. Review and trust the new `PermissionRequest` and `PreToolUse` commands. If a hook command changes later, review and trust it again. The `notify` command and hooks provide the three alerts above.

4. **Send a test alert.** This works regardless of which iTerm2 window is in front. Confirm the Bark notification on your phone; check Apple Watch notification settings if you expect it on your watch.

   ```sh
   /usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --test
   ```

5. **Check the real workflow.** Start Codex CLI in iTerm2, send a request, then switch to another window or app. You should get an alert when the turn finishes. Return to that iTerm2 session to confirm event alerts are suppressed. Check permission and input or choice alerts when those events occur.

### Optional proxy

Bark is contacted directly by default. If your network needs a proxy, pass the same address during installation and testing:

```sh
/usr/bin/python3 install.py --proxy http://127.0.0.1:7890
/usr/bin/python3 "${CODEX_HOME:-$HOME/.codex}/hooks/codex_note_reminder.py" --test --proxy http://127.0.0.1:7890
```

Do not include credentials in the proxy URL. Re-running the installer updates the program and proxy setting.

### Uninstall and local data

```sh
/usr/bin/python3 install.py --uninstall
```

Uninstall removes this tool's configuration and program but retains the Bark key. Delete `${CODEX_HOME:-$HOME/.codex}/bark_device_key` yourself if you no longer need it. Configuration backups are kept in `${CODEX_HOME:-$HOME/.codex}/backups/codex-note-reminder/`.
