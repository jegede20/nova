"""The agent loop: tool calling, confirmations, cancellation, AI failure handling."""

from __future__ import annotations

from nova.ai.agent import NovaAgent
from nova.ai.provider import AIError, AIProvider, AIResponse, AIUnavailable, ToolCall
from nova.core.tools.registry import ToolRegistry, ToolResult


class ScriptedProvider(AIProvider):
    """Replays a fixed list of responses so tests never touch the network."""

    name = "scripted"

    def __init__(self, responses):
        super().__init__("test-key", "test-model")
        self.responses = list(responses)
        self.calls = 0

    def available(self):
        return True

    async def chat(self, messages, tools=None, timeout=60.0):
        self.calls += 1
        if not self.responses:
            return AIResponse(text="Done.")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class DeadProvider(AIProvider):
    name = "dead"

    def available(self):
        return True

    async def chat(self, messages, tools=None, timeout=60.0):
        raise AIUnavailable("I can't reach the AI service.")


def build_agent(db, settings, provider, confirm=None):
    reg = ToolRegistry()

    state = {"opened": [], "deleted": []}

    @reg.tool("open_app", "Open an app", {"name": {"type": "string", "required": True}})
    def open_app(name: str):
        state["opened"].append(name)
        return ToolResult.success(f"Opening {name}.")

    @reg.tool("delete_file", "Delete files",
              {"paths": {"type": "array", "items": {"type": "string"}, "required": True}})
    def delete_file(paths):
        state["deleted"].extend(paths)
        return ToolResult.success(f"Deleted {len(paths)} files.")

    @reg.tool("broken_tool", "Always fails", {})
    def broken():
        raise RuntimeError("disk on fire")

    agent = NovaAgent(reg, settings, db, provider=provider, confirm_fn=confirm)
    return agent, state


async def test_agent_executes_a_tool_call(db, settings):
    provider = ScriptedProvider([
        AIResponse(tool_calls=[ToolCall("1", "open_app", {"name": "Chrome"})]),
        AIResponse(text="Chrome is open."),
    ])
    agent, state = build_agent(db, settings, provider)
    reply = await agent.handle("open chrome")
    assert reply.ok
    assert state["opened"] == ["Chrome"]
    assert reply.text == "Chrome is open."


async def test_high_risk_tool_blocked_without_confirmation(db, settings):
    provider = ScriptedProvider([
        AIResponse(tool_calls=[ToolCall("1", "delete_file", {"paths": ["/tmp/a"]})]),
        AIResponse(text="I didn't delete anything."),
    ])
    agent, state = build_agent(db, settings, provider, confirm=None)
    await agent.handle("delete that file")
    assert state["deleted"] == []   # denied by default when no UI can ask


async def test_high_risk_runs_after_approval(db, settings):
    async def approve(decision, tool, args):
        return True

    provider = ScriptedProvider([
        AIResponse(tool_calls=[ToolCall("1", "delete_file", {"paths": ["/tmp/a"]})]),
        AIResponse(text="Deleted."),
    ])
    agent, state = build_agent(db, settings, provider, confirm=approve)
    await agent.handle("delete that file")
    assert state["deleted"] == ["/tmp/a"]


async def test_declined_confirmation_is_reported_honestly(db, settings):
    async def decline(decision, tool, args):
        return False

    provider = ScriptedProvider([
        AIResponse(tool_calls=[ToolCall("1", "delete_file", {"paths": ["/tmp/a"]})]),
        AIResponse(text="Okay, I left them alone."),
    ])
    agent, state = build_agent(db, settings, provider, confirm=decline)
    reply = await agent.handle("delete that file")
    assert state["deleted"] == []
    assert reply.ok
    rows = db.query("SELECT * FROM permissions WHERE decision='deny'")
    assert rows


async def test_tool_exception_does_not_crash_the_agent(db, settings):
    provider = ScriptedProvider([
        AIResponse(tool_calls=[ToolCall("1", "broken_tool", {})]),
        AIResponse(text="That tool failed."),
    ])
    agent, _ = build_agent(db, settings, provider)
    reply = await agent.handle("run the broken tool")
    assert reply.ok
    assert "failed" in reply.text.lower()


async def test_step_limit_prevents_infinite_loops(db, settings):
    looping = [AIResponse(tool_calls=[ToolCall(str(i), "open_app", {"name": "Chrome"})])
               for i in range(40)]
    agent, _ = build_agent(db, settings, ScriptedProvider(looping))
    reply = await agent.handle("keep going forever")
    assert reply.ok is False
    assert "too many steps" in reply.text.lower()


async def test_network_failure_falls_back_to_local_commands(db, settings):
    agent, state = build_agent(db, settings, DeadProvider(None, "x"))
    reply = await agent.handle("open chrome")
    assert reply.used_ai is False
    assert state["opened"] == ["chrome"]


async def test_network_failure_on_complex_request_is_explained(db, settings):
    agent, _ = build_agent(db, settings, DeadProvider(None, "x"))
    reply = await agent.handle("summarise every invoice from last quarter")
    assert reply.ok is False
    assert "can't reach" in reply.text.lower() or "ai service" in reply.text.lower()


async def test_api_error_is_surfaced_not_hidden(db, settings):
    provider = ScriptedProvider([AIError("The AI provider rejected the API key.")])
    agent, _ = build_agent(db, settings, provider)
    reply = await agent.handle("do something clever with my files")
    assert reply.ok is False
    assert "api key" in reply.text.lower()


async def test_cancellation_mid_run_stops_further_tools(db, settings):
    """A stop issued while Nova is working must prevent the remaining steps."""

    class CancellingProvider(ScriptedProvider):
        def __init__(self, agent_ref, responses):
            super().__init__(responses)
            self.agent_ref = agent_ref

        async def chat(self, messages, tools=None, timeout=60.0):
            response = await super().chat(messages, tools, timeout)
            self.agent_ref["agent"].cancel()   # user hits Stop right now
            return response

    ref: dict = {}
    provider = CancellingProvider(ref, [
        AIResponse(tool_calls=[ToolCall("1", "open_app", {"name": "Chrome"})]),
        AIResponse(text="never reached"),
    ])
    agent, state = build_agent(db, settings, provider)
    ref["agent"] = agent
    reply = await agent.handle("open chrome then do more things")
    assert state["opened"] == []            # cancelled before the tool ran
    assert reply.ok is False
    assert "stopped" in reply.text.lower()


async def test_new_command_clears_a_previous_stop(db, settings):
    provider = ScriptedProvider([
        AIResponse(tool_calls=[ToolCall("1", "open_app", {"name": "Chrome"})]),
        AIResponse(text="Chrome is open."),
    ])
    agent, state = build_agent(db, settings, provider)
    agent.cancel()
    reply = await agent.handle("open chrome")
    assert reply.ok and state["opened"] == ["Chrome"]


async def test_empty_command_asks_for_a_repeat(db, settings):
    agent, _ = build_agent(db, settings, ScriptedProvider([]))
    reply = await agent.handle("   ")
    assert reply.ok is False
    assert "again" in reply.text.lower()


async def test_history_is_recorded(db, settings):
    provider = ScriptedProvider([
        AIResponse(tool_calls=[ToolCall("1", "open_app", {"name": "Chrome"})]),
        AIResponse(text="Chrome is open."),
    ])
    agent, _ = build_agent(db, settings, provider)
    await agent.handle("open chrome")
    kinds = {r["kind"] for r in db.recent_history(20)}
    assert {"command", "action", "response"} <= kinds


# ---------- planner gating (each plan costs an extra API call) ----------
def test_simple_commands_do_not_trigger_planning():
    """Regression: 'open downloads' matched the verb 'download' as a substring."""
    for command in ["open downloads", "open my downloads folder", "open chrome",
                    "create a folder called Test", "download all the pdfs",
                    "find my latest pdf", "search for news"]:
        assert NovaAgent._looks_complex(command) is False, command


def test_multi_step_commands_do_trigger_planning():
    for command in ["find my latest pdf and move it to documents",
                    "open chrome and search for bitcoin",
                    "find the pdf, rename it and move it to Reports"]:
        assert NovaAgent._looks_complex(command) is True, command
