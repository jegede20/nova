"""NovaCore: the single object that owns every subsystem.

The UI holds one NovaCore and talks to it; nothing in the UI touches tools,
providers or the database directly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from ..ai.agent import AgentEvent, AgentReply, AgentState, NovaAgent
from ..ai.provider import AIError, build_vision_provider, encode_image
from ..voice.listener import VoiceCommand, VoiceListener
from ..voice.speaker_id import SpeakerVerifier
from ..voice.stt import SpeechToText
from ..voice.tts import TextToSpeech
from ..winplat.notifications import Notifier
from .database import Database, get_db
from .logging_setup import get_logger, setup_logging
from .safety import SafetyDecision
from .settings import Settings
from .tasks import TaskManager
from .tools import apps, browser, files, screen, system  # noqa: F401  (registers tools)
from .tools.registry import registry
from .watchers import WatcherService

log = get_logger("core")

ConfirmHandler = Callable[[SafetyDecision, str, dict], Any]


class NovaCore:
    def __init__(self, db: Database | None = None) -> None:
        setup_logging()
        self.db = db or get_db()
        self.settings = Settings(self.db)
        self.registry = registry

        self.tts = TextToSpeech(self.settings)
        self.notifier = Notifier(self.settings, self.db)
        self.tasks = TaskManager(self.db)
        self.watchers = WatcherService(self.db, notifier=self.notifier.notify)

        self.stt = SpeechToText(self.settings)
        self.verifier = SpeakerVerifier(self.settings)
        self.listener: VoiceListener | None = None

        self.agent = NovaAgent(
            registry=self.registry,
            settings=self.settings,
            db=self.db,
            confirm_fn=self._confirm,
            event_fn=self._on_agent_event,
        )

        # UI callbacks (set by the main window)
        self.on_event: Callable[[AgentEvent], None] | None = None
        self.on_reply: Callable[[AgentReply], None] | None = None
        self.on_listen_state: Callable[[str], None] | None = None
        self.confirm_handler: ConfirmHandler | None = None

        self.state = AgentState.IDLE
        self.listening = False
        self.started_at = time.time()
        self._wire_services()

    # ---------------------------------------------------------------- setup
    def _wire_services(self) -> None:
        browser.session.configure(self.settings)
        screen.set_vision_hook(self._vision)
        system.bind_services(
            task_manager=self.tasks,
            watchers=self.watchers,
            notifier=self.notifier,
            tts=self.tts,
            background_runner=self.run_background_command,
            status_fn=self.status,
        )
        self.watchers.notifier = self.notifier.notify

    def start(self) -> None:
        self.tasks.start()
        self.tasks.run_soon(self.watchers.run())
        if self.settings.get("voice_activation", True):
            self.start_listening()
        self.db.add_history("system", detail="Nova started", status="ok")
        log.info("Nova core started (provider=%s)", self.settings.get("ai_provider"))

    def shutdown(self) -> None:
        log.info("Nova shutting down")
        try:
            self.stop_listening()
            self.watchers.stop()
            if browser.session.active:
                fut = self.tasks.run_soon(browser.session.close())
                try:
                    fut.result(timeout=5)
                except Exception:
                    pass
            self.tasks.stop()
            self.tts.shutdown()
            self.db.add_history("system", detail="Nova stopped", status="ok")
        except Exception:
            log.exception("Error during shutdown")

    # ---------------------------------------------------------------- voice
    def start_listening(self) -> tuple[bool, str]:
        if self.listener is None:
            self.listener = VoiceListener(
                self.settings, self.stt, self.verifier,
                on_command=self._on_voice_command,
                on_state=self._on_listen_state,
            )
        ok, msg = self.listener.start()
        self.listening = ok
        if not ok:
            log.warning("Voice activation unavailable: %s", msg)
        return ok, msg

    def stop_listening(self) -> None:
        if self.listener:
            self.listener.stop()
        self.listening = False

    def pause_listening(self) -> None:
        if self.listener and self.listener.running:
            self.listener.pause()
        self.listening = False

    def resume_listening(self) -> tuple[bool, str]:
        if self.listener and self.listener.running:
            self.listener.resume()
            self.listening = True
            return True, "Listening again."
        return self.start_listening()

    def _on_listen_state(self, state: str) -> None:
        if self.on_listen_state:
            self.on_listen_state(state)

    def _on_voice_command(self, cmd: VoiceCommand) -> None:
        """Voice pipeline gate: verify speaker, check confidence, then run."""
        if not cmd.authorized:
            log.info("Ignored command from an unrecognised voice (score %.2f)", cmd.speaker_score)
            self.db.add_history("command", command="(ignored)", status="denied",
                                detail=f"Unrecognised voice, score {cmd.speaker_score:.2f}")
            self._emit(AgentEvent("error", "I didn't recognise that voice, so I ignored the command."))
            return
        if not cmd.text.strip():
            self.say("I didn't catch a command. Please try again.")
            return
        if cmd.confidence < 0.55:
            msg = "I'm not confident I understood that. Could you say it again?"
            self._emit(AgentEvent("error", msg))
            self.say(msg)
            return
        self.submit_command(cmd.text)

    # ---------------------------------------------------------------- commands
    def submit_command(self, text: str, speak: bool = True) -> Any:
        """Run a command on the background loop. Returns a concurrent Future."""
        async def run() -> AgentReply:
            reply = await self.agent.handle(text)
            if speak:
                self.say(reply.text)
            if self.on_reply:
                self.on_reply(reply)
            return reply

        return self.tasks.run_soon(run())

    def run_background_command(self, title: str, instruction: str) -> int:
        """Used by the create_task tool: run an instruction as a cancellable task."""
        async def job(handle: Any) -> str:
            await handle.checkpoint()
            handle.progress(0.1, f"Started: {title}")
            # Reuse the already-configured provider so background work behaves
            # exactly like foreground work.
            sub_agent = NovaAgent(self.registry, self.settings, self.db,
                                  provider=self.agent.provider,
                                  confirm_fn=self._confirm, event_fn=self._on_agent_event)
            reply = await sub_agent.handle(instruction, speak_plan=False)
            await handle.checkpoint()
            handle.progress(1.0)
            if not reply.ok:
                raise RuntimeError(reply.text)
            self.notifier.notify(f"Nova finished: {title}", reply.text[:200])
            self.say(f"Finished {title}.")
            return reply.text

        return self.tasks.submit(title, job, command=instruction)

    def cancel_everything(self) -> str:
        self.agent.cancel()
        count = self.tasks.cancel_all()
        self.tts.stop()
        return f"Stopped. {count} task{'s' if count != 1 else ''} cancelled." if count else "Stopped."

    # ---------------------------------------------------------------- vision
    async def _vision(self, image_path: str, question: str) -> str:
        if not self.settings.get("allow_screen_capture", True):
            raise AIError("Screen capture is disabled in Privacy settings.")
        provider = build_vision_provider(self.settings)
        if not provider.available():
            raise AIError("No AI provider is configured for screen understanding.")
        if not provider.supports_vision:
            raise AIError(f"{provider.name} doesn't support image understanding.")
        b64 = encode_image(image_path)
        prompt = (
            "You are looking at a Windows screen. Answer briefly and concretely. "
            "When asked where to click, name the visible control rather than raw coordinates.\n\n" + question
        )
        return await provider.describe_image(b64, prompt)

    # ---------------------------------------------------------------- events
    def _on_agent_event(self, event: AgentEvent) -> None:
        if event.kind == "state":
            try:
                self.state = AgentState(event.text)
            except ValueError:
                pass
        self._emit(event)

    def _emit(self, event: AgentEvent) -> None:
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                log.exception("UI event handler failed")

    async def _confirm(self, decision: SafetyDecision, tool: str, args: dict) -> bool:
        """Route confirmations to the UI; deny if nothing can ask the user."""
        if self.confirm_handler is None:
            log.warning("No confirmation UI available; denying %s", tool)
            return False
        self.say(self._confirm_sentence(decision))
        result = self.confirm_handler(decision, tool, args)
        if asyncio.isfuture(result) or asyncio.iscoroutine(result):
            return bool(await result)
        return bool(result)

    @staticmethod
    def _confirm_sentence(decision: SafetyDecision) -> str:
        return f"I'm waiting for your confirmation. {decision.summary}?"

    # ---------------------------------------------------------------- misc
    def say(self, text: str) -> None:
        if text and self.settings.get("tts_enabled", True):
            self.tts.speak(text)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "listening": self.listening and not (self.listener.paused if self.listener else False),
            "tasks": len(self.tasks.active()),
            "watchers": len(self.watchers.list(active_only=True)),
            "provider": self.settings.get("ai_provider", "none"),
            "model": self.settings.get("ai_model", ""),
            "voice_enrolled": self.verifier.enrolled,
            "uptime_s": int(time.time() - self.started_at),
        }

    def capability_report(self) -> list[dict[str, Any]]:
        """What's installed and what isn't, for the dashboard and About page."""
        def has(mod: str) -> bool:
            import importlib.util

            return importlib.util.find_spec(mod) is not None

        provider_ready = False
        try:
            from ..ai.provider import build_provider

            provider_ready = build_provider(self.settings).available()
        except Exception:
            pass

        return [
            {"name": "AI provider", "ok": provider_ready,
             "detail": f"{self.settings.get('ai_provider')} / {self.settings.get('ai_model')}"
                       if provider_ready else "Add an API key in Settings"},
            {"name": "Speech to text", "ok": has("faster_whisper"), "detail": "pip install faster-whisper"},
            {"name": "Microphone", "ok": has("sounddevice"), "detail": "pip install sounddevice"},
            {"name": "Voice output", "ok": has("pyttsx3"), "detail": "pip install pyttsx3"},
            {"name": "Browser automation", "ok": has("playwright"), "detail": "playwright install chromium"},
            {"name": "Screen & input", "ok": has("pyautogui"), "detail": "pip install pyautogui"},
            {"name": "UI automation", "ok": has("uiautomation"), "detail": "pip install uiautomation (Windows)"},
            {"name": "Voice profile", "ok": self.verifier.enrolled, "detail": "Enroll from Settings"},
        ]
