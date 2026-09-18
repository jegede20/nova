# Nova

A voice-controlled AI agent for Windows. Nova lives in the system tray, listens for
“Hey Nova”, verifies it's really you, then operates your PC through a controlled set
of tools — opening apps, managing files, driving the browser, watching pages, and
running long jobs in the background.

```
USER → VOICE → SPEAKER VERIFICATION → SPEECH-TO-TEXT → AI UNDERSTANDING
     → ACTION PLAN → SAFETY CHECK → CONTROLLED TOOL → VERIFY → RESPONSE
```

The AI never gets a shell. It can only request tools by name, with validated
arguments, and every risky action is gated behind your explicit approval.

---

## Quick start

> **New to Python or setting this up for the first time?**
> Follow **[SETUP_WINDOWS.md](SETUP_WINDOWS.md)** instead — a click-by-click guide
> that assumes no prior experience. Or just double-click `setup_nova.bat`.

```bat
git clone <your-repo> nova
cd nova
setup_nova.bat          :: creates .venv and installs everything
start_nova.bat          :: launch
```

Or manually:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python run_nova.py
```

Run `check_nova.bat` any time to see what is installed and what is missing.

Nova opens its dashboard and places an icon in the system tray. Closing the window
keeps it running; exit from the tray menu.

| Command | What it does |
| --- | --- |
| `python run_nova.py` | Start with the window open |
| `python run_nova.py --tray` | Start hidden in the tray (used at Windows login) |

## Configure the AI provider

Settings → **AI provider**. Nova ships with four adapters and any
OpenAI-compatible endpoint works via `custom`.

| Provider | API key needed | Notes |
| --- | --- | --- |
| `openai` | yes | `gpt-4o-mini`. Supports vision |
| `anthropic` | yes | `claude-3-5-sonnet-latest`. Supports vision |
| `groq` | yes | `openai/gpt-oss-20b` + `qwen/qwen3.6-27b` for vision. Free tier available, very fast |
| `ollama` | **no** | Fully local, e.g. `llama3.1`. No data leaves your PC |

Selecting a provider fills in a working model and vision model automatically.

Paste the key into Settings and press **Test connection**. Keys go to the Windows
Credential Manager — never into the database or logs. `OPENAI_API_KEY` and friends
are also picked up from the environment.

Nova still works without any AI: “open Chrome”, “open Downloads”, “create a folder
called X”, “find my latest PDF” and “stop” are handled by a local pattern matcher.

## Enroll your voice

Sidebar → **Voice enrollment** → read four short phrases aloud.

Nova stores a mathematical voice signature, not recordings; the audio is discarded
once the signature is computed. Adjust strictness in Settings, or re-enroll any time.

> Voice matching is a convenience filter, not security. Risky actions always require
> on-screen confirmation regardless of who is speaking.

## Try it

```
Hey Nova, open Chrome.
Hey Nova, open my Downloads folder.
Hey Nova, create a folder called Hackathon Projects on my Desktop.
Hey Nova, find the PDF I downloaded yesterday and move it to Documents.
Hey Nova, what is on my screen?
Hey Nova, open Chrome and search for the latest Arc testnet documentation.
Hey Nova, watch this webpage and tell me when it changes.
Hey Nova, download all the PDFs from this page into a folder called Reports.
Hey Nova, what tasks are running?
Hey Nova, stop.
```

## Safety model

| Level | Behaviour | Examples |
| --- | --- | --- |
| **Low** | Runs immediately | open app/folder, search files, screenshot |
| **Medium** | Confirms (toggleable) | move/copy/rename, close app, click, type |
| **High** | Always confirms | delete, empty recycle bin, uploads, purchases, PowerShell |
| **Blocked** | Refused outright | `C:\Windows`, `Program Files`, typing passwords or keys |

Bulk operations escalate automatically: moving more files than your threshold, or
clicking a button whose label reads *Place order* / *Delete account*, jumps to High.

Confirmations spell out the consequence:

> “I'm about to delete 28 files from Downloads. This cannot easily be undone. Continue?”

## Layout

```
nova/
├── core/
│   ├── nova_core.py      orchestrator — owns every subsystem
│   ├── safety.py         risk levels, protected paths, confirmation rules
│   ├── tasks.py          background workers (pause/resume/cancel)
│   ├── watchers.py       website + folder monitoring
│   ├── database.py       SQLite: tasks, watchers, history, settings
│   ├── settings.py       preferences + OS credential storage
│   └── tools/            THE CONTROLLED TOOL LAYER
│       ├── registry.py   schemas, argument validation, dispatch
│       ├── apps.py       open/close/focus/detect applications
│       ├── files.py      search, open, create, rename, move, copy, delete
│       ├── screen.py     screenshots, accessibility tree, mouse/keyboard
│       ├── browser.py    Playwright automation
│       └── system.py     tasks, watchers, notifications, speech
├── ai/
│   ├── provider.py       OpenAI / Anthropic / Groq / Ollama adapters
│   ├── agent.py          reasoning loop, planner, safety gate
│   └── local_intent.py   offline command matching
├── voice/                wake word, Whisper STT, speaker ID, TTS
├── winplat/              toasts, start-with-Windows
└── ui/                   PySide6 dashboard, tray, 8 pages
```

## Privacy

- Microphone audio is transcribed locally by Whisper and never uploaded.
- No recordings are kept — enrollment stores embeddings only.
- Screenshots are sent to the AI **only** when you ask about your screen.
- Logs run through a redaction filter that strips keys, tokens and passwords.
- Everything lives in `%LOCALAPPDATA%\Nova`.

## Development

```bat
pip install -r requirements-dev.txt
pytest          :: 92 tests
ruff check .
mypy nova
```

Tests never touch the network or your real files — the AI provider is scripted and
all file operations run in temp directories.

## Known limitations

- Windows-only for app control, screen reading and startup; the core, tools, AI and
  UI layers run anywhere (tests run on Linux).
- Wake-word detection transcribes short local chunks rather than using a dedicated
  wake-word engine. Reliable and private, but it uses more CPU than Porcupine.
- Speaker verification uses a numpy spectral fingerprint unless `resemblyzer` is
  installed, which is noticeably more accurate.
- A crash marks in-flight tasks as failed rather than resuming them.
- Screen understanding needs a vision-capable model; Groq and most local models
  can't do it.
