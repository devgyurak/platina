/**
 * Platina edit guard for Pi - mirrors the Claude Code / Codex hooks.
 *
 * - tool_call (write/edit): block edits to generated agent files (edit .agents/ instead).
 * - tool_result (write/edit): run tools/guards + ruff on the edited file and append any
 *   violations to the tool result so the model fixes them immediately.
 *
 * Both delegate to tools/hooks/agent_hook.py so all agents share one implementation.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const EDIT_TOOLS = new Set(["write", "edit"]);

export default function (pi: ExtensionAPI) {
	const runHook = (mode: "pre" | "post", path: string, signal?: AbortSignal) =>
		pi.exec("uv", ["run", "--quiet", "python", "tools/hooks/agent_hook.py", mode, "--paths", path], {
			signal,
			timeout: 60_000,
		});

	pi.on("tool_call", async (event, ctx) => {
		if (!EDIT_TOOLS.has(event.toolName)) return undefined;
		const path = String((event.input as { path?: string }).path ?? "");
		const result = await runHook("pre", path, ctx.signal);
		if (result.code === 2) {
			return { block: true, reason: result.stderr.trim() };
		}
		return undefined;
	});

	pi.on("tool_result", async (event, ctx) => {
		if (!EDIT_TOOLS.has(event.toolName) || event.isError) return undefined;
		const path = String((event.input as { path?: string }).path ?? "");
		const result = await runHook("post", path, ctx.signal);
		if (result.code !== 2) return undefined;
		return {
			content: [...event.content, { type: "text" as const, text: `\n\n[platina guard]\n${result.stderr.trim()}` }],
		};
	});
}
