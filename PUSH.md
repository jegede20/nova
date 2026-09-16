# Pushing Nova to your GitHub repo

Run these on **your Windows PC**, in the Nova folder.
(Open the folder, type `cmd` in the address bar, press Enter.)

---

## Step 1 — Set your identity (do this first)

The commits are currently authored by a placeholder. Set your real details so
GitHub links the commits to your account:

```bat
git config user.name  "Your Name"
git config user.email "your-github-email@example.com"
```

Use the email tied to your GitHub account, otherwise the commits appear as
"unknown author".

### Rewrite the existing commits to use it

```bat
git -c rebase.instructionFormat="%s" rebase --root --exec "git commit --amend --no-edit --reset-author"
```

Then confirm:

```bat
git log --format="%an <%ae>" | sort -u
```

> Prefer to skip this? Fine — the code is identical either way, the commits
> just won't show your avatar.

---

## Step 2 — Connect your repo

Replace the URL with your actual repository:

```bat
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git remote -v
```

> Already added a remote and need to change it?
> `git remote set-url origin https://github.com/YOUR-USERNAME/YOUR-REPO.git`

---

## Step 3 — Match the branch name

GitHub defaults to `main`; this repo is on `master`. Rename it:

```bat
git branch -M main
```

---

## Step 4 — Push

```bat
git push -u origin main
```

A browser window opens asking you to sign in to GitHub. Approve it.

> **If it asks for a password in the terminal:** GitHub no longer accepts
> account passwords. Either install **Git Credential Manager** (bundled with
> Git for Windows — reinstall and keep the default options), or create a
> Personal Access Token at
> **github.com → Settings → Developer settings → Personal access tokens →
> Tokens (classic)**, tick the `repo` scope, and paste the token as the password.

---

## If the repo already has files

If you created the repo with a README or .gitignore, the push is rejected
because the histories differ. Merge them first:

```bat
git pull origin main --allow-unrelated-histories
git push -u origin main
```

If Git opens a text editor asking for a merge message, press `Esc`, type
`:wq`, and press Enter.

**Only if the remote repo is empty and you want to overwrite it:**

```bat
git push -u origin main --force
```

Force-push destroys whatever is on the remote. Don't use it otherwise.

---

## Step 5 — Verify

Refresh the repo page on GitHub. You should see 63 files, the README rendered
on the front page, and your 5 commits.

Check that these are **absent** (they're in `.gitignore` and must never appear):

- `.venv/`
- `secrets.json`
- any `.db` or `.log` file

---

## Everyday use after this

```bat
git add -A
git commit -m "Describe what you changed"
git push
```

---

## Because the repo is public

- **Never commit your API key.** Nova stores it in Windows Credential Manager,
  not in any file, so this is already safe — just don't paste a key into the
  code or README.
- If you ever do leak a key, revoke it immediately at
  platform.openai.com/api-keys. Deleting the commit is not enough; it stays in
  the history.
- Consider adding a note to the README that this software controls a PC, so
  anyone running it understands what it does.
