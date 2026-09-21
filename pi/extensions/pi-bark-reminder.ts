import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type ReminderEvent = "agent_settled" | "ui_prompt_start";
type LaunchNotifier = (event: ReminderEvent, cwd: string) => void;

const notifierPath = join(dirname(fileURLToPath(import.meta.url)), "..", "bark_notify.py");

export function launchNotifier(event: ReminderEvent, cwd: string): void {
	const child = spawn("/usr/bin/python3", [notifierPath, JSON.stringify({ event, cwd })], {
		cwd,
		detached: false,
		stdio: "ignore",
	});
	child.on("error", () => {});
	child.unref();
}

export function registerReminder(pi: ExtensionAPI, launch: LaunchNotifier = launchNotifier): void {
	pi.on("agent_settled", (_event, ctx) => {
		launch("agent_settled", ctx.cwd);
	});

	pi.on("ui_prompt_start", (_event, ctx) => {
		launch("ui_prompt_start", ctx.cwd);
	});
}

export default function piBarkReminder(pi: ExtensionAPI): void {
	registerReminder(pi);
}
