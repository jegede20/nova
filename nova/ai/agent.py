"""Nova's reasoning loop.

    command -> understand -> plan -> safety check -> tool -> verify -> respond

The agent never executes anything itself: it asks the registry, and every call
passes the SafetyGate first. Confirmations are delegated to a callback so the UI
(or a test) decides how the user answers.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.database import Database
from ..core.logging_setup import get_logger
from ..core.safety import Risk, SafetyDecision, SafetyGate
from ..core.settings import Settings
from ..core.tools.registry import ToolRegistry, ToolResult
from .local_intent import interpret, offline_reply
from .provider import AIError, AIProvider, AIUnavailable, build_provider

log = get_logger("agent")

SYSTEM_PROMPT = """You are Nova, a voice assistant that operates a Windows PC for one user.

Rules:
- Use the provided tools to do real work. Never claim something happened unless a tool confirmed it.
- Prefer finding a file before acting on it. Never invent file paths.
- If a request is ambiguous (several matching files or apps), ask one short clarifying question instead of guessing.
- Break complex requests into tool calls, one step at a time, using earlier results.
- For long jobs (downloading many files, monitoring), create a background task or watcher instead of blocking.
- Destructive or sensitive actions are gated by the user's confirmation system. If a tool reports it was denied, stop and say so.
- Keep spoken replies to one or two short natural sentences. No markdown, no lists, no emoji.
- If a tool fails, explain the problem plainly. Never pretend it worked.
"""

PLANNER_PROMPT = """Break the user's request into a short numbered action plan.
Return JSON only: {"complex": true|false, "steps": ["...", "..."]}
Use "complex": false with an empty list when the request is a single obvious action.
Each step must be a short imperative phrase describing an operation (max 8 words). Maximum 8 steps.
Do not explain your reasoning."""


class AgentState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_CONFIRMATION = "waiting_confirmation"
    SPEAKING = "speaking"
    FAILED = "failed"


@dataclass
class AgentEvent:
    kind: str                # state | plan | tool | result | message | error | confirm
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


ConfirmFn = Callable[[SafetyDecision, str, dict], Awaitable[bool]]
EventFn = Callable[[AgentEvent], None]


@dataclass
class AgentReply:
    text: str
    ok: bool = True
    plan: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    used_ai: bool = True


class NovaAgent:
    MAX_STEPS = 12  # hard cap so a confused model can't loop forever

    def __init__(
        self,
        registry: ToolRegistry,
        settings: Settings,
        db: Database,
        provider: AIProvider | None = None,
        confirm_fn: ConfirmFn | None = None,
        event_fn: EventFn | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.db = db
        self.gate = SafetyGate(settings)
        self._provider = provider
        self.confirm_fn = confirm_fn
        self.event_fn = event_fn
        self.state = AgentState.IDLE
        self._cancel = asyncio.Event()
        self.history: list[dict] = []

    # ---------- plumbing ----------
    @property
    def provider(self) -> AIProvider:
        if self._provider is None:
            self._provider = build_provider(self.settings)
        return self._provider

    def reload_provider(self) -> None:
        self._provider = None

    def emit(self, kind: str, text: str = "", **data: Any) -> None:
        if self.event_fn:
            try:
                self.event_fn(AgentEvent(kind, text, data))
            except Exception:
                log.exception("An event listener raised")

    def set_state(self, state: AgentState) -> None:
        self.state = state
        self.emit("state", state.value)

    def cancel(self) -> None:
        """Stop the current run as soon as it reaches a safe point."""
        self._cancel.set()
        self.emit("message", "Stopping.")

    def _check_cancel(self) -> bool:
        return self._cancel.is_set()

    # ---------- main entry ----------
    async def handle(self, command: str, speak_plan: bool = True) -> AgentReply:
        self._cancel.clear()
        command = (command or "").strip()
        if not command:
            return AgentReply("I didn't catch that. Could you say it again?", ok=False)

        self.db.add_history("command", command=command, detail="User command")
        self.emit("message", command, role="user")

        # 1. Offline-capable shortcuts first: fast, private, no API cost.
        local = interpret(command)
        if local and local.tool == "cancel_all":
            self.cancel()
            return AgentReply("Stopped.", actions=[])

        provider_ok = self.provider.available()
        if not provider_ok:
            return await self._run_local(command, local, reason="no_provider")

        try:
            return await self._run_ai(command, speak_plan=speak_plan)
        except AIUnavailable as e:
            log.warning("AI unavailable: %s", e)
            self.emit("error", str(e))
            return await self._run_local(command, local, reason="offline", note=str(e))
        except AIError as e:
            self.set_state(AgentState.FAILED)
            self.db.add_history("error", command=command, detail=str(e), status="failed")
            return AgentReply(str(e), ok=False)

    # ---------- offline path ----------
    async def _run_local(self, command: str, local: Any, reason: str, note: str = "") -> AgentReply:
        if local is None:
            msg = note or offline_reply(command)
            if reason == "no_provider":
                msg = ("No AI provider is configured yet, so I can only do simple things like "
                       "opening apps and folders. You can add an API key in Settings.")
            self.db.add_history("response", command=command, detail=msg, status="failed")
            return AgentReply(msg, ok=False, used_ai=False)

        self.set_state(AgentState.EXECUTING)
        result, decision = await self._execute_tool(local.tool, local.args, command)
        self.set_state(AgentState.IDLE)
        prefix = "" if reason == "no_provider" else ""
        return AgentReply(prefix + result.message, ok=result.ok, used_ai=False,
                          actions=[{"tool": local.tool, "ok": result.ok, "message": result.message}])

    # ---------- AI path ----------
    async def _run_ai(self, command: str, speak_plan: bool = True) -> AgentReply:
        self.set_state(AgentState.THINKING)
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT + self._context_block()},
            *self.history[-8:],
            {"role": "user", "content": command},
        ]
        tools = self.registry.schemas()
        plan: list[str] = []
        actions: list[dict] = []

        # Optional plan for complex requests (shown in the UI, never chain-of-thought).
        if self._looks_complex(command):
            plan = await self._make_plan(command)
            if plan:
                self.set_state(AgentState.PLANNING)
                self.emit("plan", "Action plan", steps=plan)

        self.set_state(AgentState.EXECUTING)
        for _step in range(self.MAX_STEPS):
            if self._check_cancel():
                return AgentReply("Stopped before finishing.", ok=False, plan=plan, actions=actions)

            response = await self.provider.chat(messages, tools)

            if not response.wants_tools:
                text = (response.text or "Done.").strip()
                self.history.append({"role": "user", "content": command})
                self.history.append({"role": "assistant", "content": text})
                self.db.add_history("response", command=command, detail=text, status="ok")
                self.set_state(AgentState.IDLE)
                return AgentReply(text, ok=True, plan=plan, actions=actions)

            messages.append({
                "role": "assistant",
                "content": response.text or "",
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                } for tc in response.tool_calls],
            })

            for tc in response.tool_calls:
                if self._check_cancel():
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps({"ok": False, "message": "Cancelled by the user."})})
                    continue
                self.emit("tool", tc.name, args=tc.arguments)
                result, decision = await self._execute_tool(tc.name, tc.arguments, command)
                actions.append({"tool": tc.name, "ok": result.ok, "message": result.message,
                                "risk": decision.risk.value if decision else "low"})
                self.emit("result", result.message, tool=tc.name, ok=result.ok)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result.to_llm())[:4000]})

        # Ran out of steps.
        self.set_state(AgentState.FAILED)
        msg = "I took too many steps without finishing, so I stopped. Could you narrow the request?"
        self.db.add_history("error", command=command, detail=msg, status="failed")
        return AgentReply(msg, ok=False, plan=plan, actions=actions)

    # ---------- planning ----------
    @staticmethod
    def _looks_complex(command: str) -> bool:
        """Only plan multi-step requests -- planning costs an extra API call.

        Matches whole words: "open downloads" must not count "download" as a
        second verb just because it appears inside "downloads".
        """
        import re as _re

        lowered = command.lower()
        verbs = ["find", "create", "make", "move", "rename", "download", "open",
                 "delete", "copy", "watch", "search"]
        pattern = r"\b(" + "|".join(verbs) + r")(s|es|ed|ing)?\b"
        verb_count = len(_re.findall(pattern, lowered))
        has_connector = bool(_re.search(r"\b(and then|then|and|after that)\b", lowered))
        return verb_count >= 2 and has_connector

    async def _make_plan(self, command: str) -> list[str]:
        try:
            resp = await self.provider.chat(
                [{"role": "system", "content": PLANNER_PROMPT}, {"role": "user", "content": command}],
                timeout=25.0,
            )
            raw = resp.text.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
            data = json.loads(raw)
            if data.get("complex") and isinstance(data.get("steps"), list):
                return [str(s)[:90] for s in data["steps"]][:8]
        except (AIError, json.JSONDecodeError, KeyError, ValueError):
            log.debug("Planner produced no usable plan; continuing without one.")
        return []

    # ---------- execution with safety ----------
    async def _execute_tool(self, name: str, args: dict, command: str = "") -> tuple[ToolResult, SafetyDecision | None]:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult.fail(f"I don't have a tool called '{name}'."), None

        try:
            clean = self.registry.validate(name, args)
        except Exception as e:
            return ToolResult.fail(str(e)), None

        decision = self.gate.evaluate(name, clean)

        if decision.risk is Risk.BLOCKED:
            self.db.add_history("action", command=command, detail=decision.reason, tool=name, status="denied")
            return ToolResult.fail(decision.reason or "That action is not allowed."), decision

        if decision.needs_confirmation:
            remembered = self.db.remembered_decision(name, _scope_of(clean))
            approved = remembered == "allow" if remembered else await self._ask_confirmation(decision, name, clean)
            if not approved:
                self.db.record_permission(name, _scope_of(clean), "deny")
                self.db.add_history("action", command=command, detail=f"Declined: {decision.summary}",
                                    tool=name, status="denied")
                return ToolResult.fail("Okay, I won't do that."), decision
            self.db.record_permission(name, _scope_of(clean), "allow")

        self.set_state(AgentState.EXECUTING)
        started = time.time()
        result = await self.registry.call(name, clean)
        elapsed = round(time.time() - started, 2)
        log.info("tool=%s ok=%s (%.2fs)", name, result.ok, elapsed)
        self.db.add_history("action", command=command, detail=result.message, tool=name,
                            status="ok" if result.ok else "failed")
        return result, decision

    async def _ask_confirmation(self, decision: SafetyDecision, tool: str, args: dict) -> bool:
        self.set_state(AgentState.WAITING_CONFIRMATION)
        self.emit("confirm", decision.summary, risk=decision.risk.value, details=decision.details, tool=tool)
        if self.confirm_fn is None:
            log.warning("No confirmation handler; refusing %s by default.", tool)
            return False
        try:
            return bool(await self.confirm_fn(decision, tool, args))
        except Exception:
            log.exception("Confirmation handler failed")
            return False

    # ---------- context ----------
    def _context_block(self) -> str:
        from ..core.paths import known_folders

        folders = ", ".join(f"{k}={v}" for k, v in list(known_folders().items())[:7])
        now = time.strftime("%A %Y-%m-%d %H:%M")
        return f"\n\nCurrent time: {now}.\nUser folders: {folders}."


def _scope_of(args: dict) -> str:
    for key in ("path", "source", "name", "paths", "target"):
        v = args.get(key)
        if isinstance(v, list):
            return str(v[0]) if v else ""
        if isinstance(v, str):
            return v
    return ""
