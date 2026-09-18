# Setting up Nova on Windows

A complete walkthrough, written for someone who has never used Python.
Total time: **15–25 minutes**, most of it waiting for downloads.

You will do five things:

1. Install Python
2. Put the Nova folder on your PC
3. Run the setup file
4. Add an AI key
5. Teach Nova your voice

---

## Before you start

| You need | Why |
| --- | --- |
| Windows 10 or 11 | Nova controls Windows apps directly |
| An internet connection | To download the installer and reach the AI |
| A microphone | Any laptop mic or headset works |
| About 3 GB free disk space | Python, the browser engine and the speech model |

---

## Step 1 — Install Python

Nova is written in Python, so Windows needs it installed first.

1. Go to **https://www.python.org/downloads/**
2. Click the big yellow **Download Python** button.
3. Open the file you just downloaded.
4. **This next part matters.** On the very first screen, tick the box at the bottom:

   > ☑ **Add python.exe to PATH**

   If you miss this, nothing else will work. It is easy to overlook.

5. Click **Install Now** and wait for it to finish.
6. Click **Close**.

**Check it worked:** press `Win + R`, type `cmd`, press Enter, then type:

```
python --version
```

You should see something like `Python 3.13.1`. Any version **3.10 or higher** is fine.

> **If you see "python is not recognized":** the PATH box wasn't ticked.
> Re-run the installer, choose **Modify**, click Next, tick
> **Add Python to environment variables**, then Finish. Close and reopen the
> black window afterwards — it only reads PATH when it starts.

---

## Step 2 — Put Nova on your PC

Pick a simple location such as `C:\Nova` or your Documents folder.

**If you have the folder already,** just copy it there.

**If you are using Git:**

```
cd C:\
git clone <your-repository-url> Nova
```

When you open the folder you should see `setup_nova.bat`, `run_nova.py`, and a
`nova` folder inside. If you instead see a single folder containing those, move
up into it — that inner folder is the real one.

---

## Step 3 — Run the setup

**Double-click `setup_nova.bat`.**

A black window opens and starts working. It will:

- check your Python version
- create a private environment so Nova's packages don't touch anything else
- install everything Nova needs
- download the browser engine used for web automation

This takes **3–10 minutes**. Lots of text scrolls past — that is normal. Some
lines may look like warnings; only stop if it ends with `[X] Setup failed`.

When it finishes you'll see:

```
  ====================================
    Setup complete.
  ====================================
```

Press any key to close it.

> **If Windows shows a blue "Windows protected your PC" box:** click
> **More info** → **Run anyway**. This appears because the file isn't
> digitally signed, not because anything is wrong.

---

## Step 4 — Start Nova

**Double-click `start_nova.bat`.**

The Nova dashboard opens, and a small circular icon appears in your system tray
(bottom-right, possibly hidden behind the `^` arrow).

At this point Nova works for basic commands but is not yet connected to an AI.
Type this into the command box and press Enter:

```
open downloads
```

Your Downloads folder should open. **That confirms the installation works.**

---

## Step 5 — Connect an AI provider

This is what lets Nova understand everyday language instead of fixed phrases.

### Choose one

| Option | Cost | Best for |
| --- | --- | --- |
| **Groq** | Free tier, no card needed | Fastest replies, and free — **recommended** |
| **OpenAI** | Pay per use, roughly $1–3/month | Slightly better at complex multi-step requests |
| **Ollama** | Free | Runs entirely on your PC. Needs a powerful machine |

### Getting a Groq key (free)

1. Go to **https://console.groq.com/keys**
2. Sign up — Google or GitHub sign-in works, **no credit card needed**.
3. Click **Create API Key**, name it "Nova", and create it.
4. **Copy it now** — it starts with `gsk_` and is shown only once.

### Putting it into Nova

1. In Nova, click **Settings** in the left sidebar.
2. Under **AI provider**, set **Provider** to `groq`.
   The model boxes fill in automatically:
   - Model: `openai/gpt-oss-20b`
   - Vision model: `qwen/qwen3.6-27b`

   Leave both as they are.
3. Paste your key into the **API key** box and press **Tab**.
4. Click **Test connection**.

You want to see green text: `Connected — openai/gpt-oss-20b replied.`

> **Which Groq model?** `openai/gpt-oss-20b` is the default: it's on the free
> tier, it's the fastest, and it handles Nova's tool calling properly. If you
> find it struggling with long multi-step requests, change Model to
> `openai/gpt-oss-120b` — smarter, still free tier, a bit slower.
>
> Avoid `llama-3.3-70b-versatile`: Groq moved it to Enterprise-only, so a
> normal key gets an error.

> Your key is stored in the **Windows Credential Manager**, the same vault
> Windows uses for saved passwords. It is never written into Nova's database
> or log files.

Now try something that needs real understanding:

```
find my most recent PDF and tell me what it's called
```

---

## Step 6 — Teach Nova your voice

1. Click **Voice enrollment** in the sidebar.
2. Click **Record sample**.
3. Read the phrase on screen aloud, normally. It records for 3.5 seconds.
4. Repeat for all four phrases.

You'll see **"Voice profile saved"** when it's done.

Now say out loud:

> **"Hey Nova, open Downloads."**

Nova should wake, act, and reply.

**What's actually stored:** a mathematical signature of your voice, not
recordings. The audio is discarded the moment the signature is calculated.

> **Important:** voice matching is a convenience filter, not a security
> measure. A determined impersonator could fool it — which is exactly why
> deleting files, purchases and uploads *always* ask for on-screen approval,
> no matter who is speaking.

---

## Step 7 — Optional finishing touches

**Start automatically with Windows**
Settings → Safety and behaviour → **Start Nova with Windows**.
Nova will then start quietly in the tray each time you log in.

**Pin it to the taskbar**
Right-click `start_nova.bat` → Show more options → Send to → Desktop.
Rename the shortcut to "Nova".

**Turn off spoken replies**
Settings → Spoken responses → untick **Speak replies out loud**.

---

## Things to try

Start with simple commands and build up:

```
Hey Nova, open Chrome.
Hey Nova, open my Downloads folder.
Hey Nova, create a folder called Projects on my Desktop.
Hey Nova, find the PDF I downloaded yesterday and move it to Documents.
Hey Nova, what is on my screen?
Hey Nova, open Chrome and search for the Arc testnet documentation.
Hey Nova, watch this webpage and tell me when it changes.
Hey Nova, what tasks are running?
Hey Nova, stop.
```

### What each colour means

| Indicator | Meaning |
| --- | --- |
| Green dot | Ready, or listening |
| Blue pulsing | Thinking or working |
| Amber | Waiting for your approval |
| Red | Something failed — it will say what |

### When Nova asks permission

For anything risky you'll get an amber box like:

> **HIGH RISK** — Delete 28 files from Downloads. This cannot easily be undone?

Nothing happens until you click **Approve**. Clicking **Cancel** stops it
completely. There is also a **Stop** button on the dashboard that halts
everything immediately.

---

## Troubleshooting

**Run `check_nova.bat` first.** It tests every part of the installation and
prints the exact command to fix anything missing.

### "python is not recognized"
The PATH box was missed during install. See the note at the end of Step 1.

### Setup failed partway through
Usually a dropped connection. Delete the `.venv` folder inside the Nova folder,
then run `setup_nova.bat` again.

### Nova doesn't respond to "Hey Nova"
Work through these in order:

1. Is **MIC ON** shown on the dashboard? If not: Settings → tick **Voice activation**.
2. Run `check_nova.bat` — it will say if the microphone or speech model is missing.
3. Windows Settings → Privacy & security → **Microphone** → ensure desktop apps
   may use it.
4. Settings → **Microphone** → choose your specific device rather than
   "System default".
5. Speak clearly and pause briefly after "Hey Nova".

**The very first voice command is slow.** Nova downloads the speech model
(~150 MB) the first time. Later commands are fast.

### "I didn't recognise that voice"
Your voice profile is too strict or was recorded in a different environment.
Settings → lower **Verification strictness** to `0.60`, or re-enroll from the
Voice enrollment page in the room you normally use.

### "I couldn't find an application called X"
Nova knows common apps by name. For unusual ones, make sure the app appears in
your Start Menu — that's where Nova looks.

### Web automation doesn't work
Open `check_nova.bat`. If it reports the browser engine is missing, open the
Nova folder, double-click `setup_nova.bat` again, or run:

```
.venv\Scripts\activate
playwright install chromium
```

### Nova disappeared
It is still running in the tray. Click the `^` arrow near the clock and
double-click the Nova icon. Closing the window never quits Nova — use
**Exit** in the tray menu for that.

### Something else went wrong
Nova writes a log to:

```
%LOCALAPPDATA%\Nova\logs\nova.log
```

Paste that path into File Explorer's address bar. The log never contains your
API keys or passwords — they are stripped out before anything is written.

---

## Everyday use

| To do this | Do that |
| --- | --- |
| Start Nova | Double-click `start_nova.bat` |
| Start hidden in the tray | Double-click `start_nova_tray.bat` |
| Diagnose a problem | Double-click `check_nova.bat` |
| Open the window again | Double-click the tray icon |
| Stop listening for a while | Right-click tray → Pause listening |
| Quit completely | Right-click tray → Exit |

---

## Where your data lives

Everything stays on your PC, in `%LOCALAPPDATA%\Nova`:

```
nova.db        your history, tasks and watchers
voice\         your voice signature (no recordings)
logs\          diagnostic log, with secrets stripped out
screenshots\   only created when you ask about your screen
```

API keys are held separately in the Windows Credential Manager.

Nova only contacts the internet when it needs to: sending your command text to
the AI, fetching a page you asked it to watch, or sending a screenshot when you
ask what's on your screen. It never streams your microphone or screen.

To erase everything: Settings → **Clear local history** and
**Delete voice profile**, or simply delete the `%LOCALAPPDATA%\Nova` folder.
