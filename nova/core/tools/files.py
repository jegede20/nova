"""File and folder tools: search, open, create, rename, copy, move, delete.

Search is scoped to the user's profile by default so Nova never crawls the whole
disk, and deletes go to the Recycle Bin when send2trash/winshell is available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from ..logging_setup import get_logger
from ..paths import IS_WINDOWS, known_folders
from .registry import ToolResult, registry

log = get_logger("tools.files")

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "AppData", "Windows", "$Recycle.Bin",
    "Program Files", "Program Files (x86)", ".venv", "venv", "site-packages",
}
MAX_SCAN = 40_000  # hard cap so a search can never run away


def resolve_path(text: str) -> Path:
    """Turn 'downloads', '~/Desktop', 'my desktop' or a real path into a Path."""
    raw = (text or "").strip().strip('"')
    lowered = raw.lower().replace("my ", "").replace("the ", "").strip()
    folders = known_folders()
    if lowered in folders:
        return folders[lowered]
    if lowered.rstrip("s") in folders:
        return folders[lowered.rstrip("s")]
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not p.is_absolute():
        # treat "Desktop/Reports" as relative to home
        candidate = Path.home() / p
        if candidate.exists() or not p.exists():
            return candidate
    return p


def _iter_files(root: Path, recursive: bool = True):
    scanned = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    scanned += 1
                    if scanned > MAX_SCAN:
                        return
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                                continue
                            if recursive:
                                stack.append(Path(entry.path))
                            yield Path(entry.path), True
                        else:
                            yield Path(entry.path), False
                    except OSError:
                        continue
        except (PermissionError, OSError):
            continue


@registry.tool(
    "find_file",
    "Search for files by name, extension or recency. Use this before opening or moving a file the user described vaguely.",
    {
        "query": {"type": "string", "description": "Part of the file name, or empty to match everything"},
        "folder": {"type": "string", "description": "Where to search: downloads, desktop, documents, home or a path", "default": "home"},
        "extension": {"type": "string", "description": "File extension filter, e.g. pdf"},
        "modified_within_days": {"type": "integer", "description": "Only files changed in the last N days"},
        "limit": {"type": "integer", "description": "Maximum results", "default": 20},
    },
    category="files",
)
def find_file(query: str = "", folder: str = "home", extension: str = "",
              modified_within_days: int = 0, limit: int = 20) -> ToolResult:
    root = resolve_path(folder)
    if not root.exists():
        return ToolResult.fail(f"The folder {root} doesn't exist.")
    needle = (query or "").lower().strip()
    ext = extension.lower().lstrip(".")
    cutoff = time.time() - modified_within_days * 86400 if modified_within_days else 0

    results = []
    for path, is_dir in _iter_files(root):
        if is_dir:
            continue
        name = path.name.lower()
        if needle and needle not in name:
            continue
        if ext and not name.endswith("." + ext):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if cutoff and st.st_mtime < cutoff:
            continue
        results.append({
            "path": str(path),
            "name": path.name,
            "size_kb": round(st.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "_mtime": st.st_mtime,
        })

    results.sort(key=lambda r: r["_mtime"], reverse=True)
    results = results[:limit]
    for r in results:
        r.pop("_mtime", None)

    if not results:
        what = f"'{query}'" if query else (f".{ext} files" if ext else "files")
        return ToolResult(False, f"I couldn't find any {what} in {root}.", {"files": [], "searched": str(root)})
    if len(results) == 1:
        return ToolResult.success(f"I found {results[0]['name']}.", files=results, count=1)
    return ToolResult.success(f"I found {len(results)} matching files.", files=results, count=len(results))


@registry.tool(
    "find_folder",
    "Search for a folder by name.",
    {"query": {"type": "string", "description": "Part of the folder name", "required": True},
     "root": {"type": "string", "description": "Where to search", "default": "home"},
     "limit": {"type": "integer", "description": "Maximum results", "default": 15}},
    category="files",
)
def find_folder(query: str, root: str = "home", limit: int = 15) -> ToolResult:
    base = resolve_path(root)
    if not base.exists():
        return ToolResult.fail(f"The folder {base} doesn't exist.")
    needle = query.lower().strip()
    hits = []
    for path, is_dir in _iter_files(base):
        if is_dir and needle in path.name.lower():
            hits.append({"path": str(path), "name": path.name})
            if len(hits) >= limit:
                break
    if not hits:
        return ToolResult(False, f"I couldn't find a folder called '{query}'.", {"folders": []})
    if len(hits) > 1:
        return ToolResult(
            True,
            f"I found {len(hits)} folders named like '{query}'. Which one do you want?",
            {"folders": hits, "needs_choice": True, "count": len(hits)},
        )
    return ToolResult.success(f"I found {hits[0]['path']}.", folders=hits, count=1)


@registry.tool(
    "recent_files",
    "List the most recently modified or created files in a folder.",
    {"folder": {"type": "string", "description": "Folder to inspect", "default": "downloads"},
     "extension": {"type": "string", "description": "Optional extension filter such as pdf"},
     "days": {"type": "integer", "description": "How far back to look", "default": 7},
     "limit": {"type": "integer", "description": "Maximum results", "default": 10}},
    category="files",
)
def recent_files(folder: str = "downloads", extension: str = "", days: int = 7, limit: int = 10) -> ToolResult:
    return find_file(query="", folder=folder, extension=extension, modified_within_days=days, limit=limit)


@registry.tool(
    "open_folder",
    "Open a folder in File Explorer.",
    {"path": {"type": "string", "description": "Folder name or full path, e.g. downloads", "required": True}},
    category="files",
)
def open_folder(path: str) -> ToolResult:
    target = resolve_path(path)
    if not target.exists():
        return ToolResult.fail(f"There is no folder at {target}.")
    if not target.is_dir():
        target = target.parent
    try:
        if IS_WINDOWS:
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return ToolResult.fail(f"I couldn't open {target}: {e}")
    return ToolResult.success(f"Opened {target.name}.", path=str(target))


@registry.tool(
    "open_file",
    "Open a file with its default Windows application.",
    {"path": {"type": "string", "description": "Full path to the file", "required": True}},
    category="files",
)
def open_file(path: str) -> ToolResult:
    target = resolve_path(path)
    if not target.exists():
        return ToolResult.fail(f"I couldn't find {target}.")
    try:
        if IS_WINDOWS:
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return ToolResult.fail(f"I couldn't open {target.name}: {e}")
    return ToolResult.success(f"Opened {target.name}.", path=str(target))


@registry.tool(
    "create_folder",
    "Create a new folder.",
    {"name": {"type": "string", "description": "New folder name", "required": True},
     "parent": {"type": "string", "description": "Where to create it: desktop, documents, downloads or a path", "default": "desktop"}},
    category="files",
)
def create_folder(name: str, parent: str = "desktop") -> ToolResult:
    base = resolve_path(parent)
    if not base.exists():
        return ToolResult.fail(f"The parent folder {base} doesn't exist.")
    safe = "".join(c for c in name if c not in '<>:"/\\|?*').strip()
    if not safe:
        return ToolResult.fail("That folder name isn't valid.")
    target = base / safe
    if target.exists():
        return ToolResult.success(f"{safe} already exists in {base.name}.", path=str(target), created=False)
    try:
        target.mkdir(parents=True)
    except OSError as e:
        return ToolResult.fail(f"I couldn't create the folder: {e}")
    if not target.exists():  # verify before reporting success
        return ToolResult.fail("The folder could not be verified after creation.")
    return ToolResult.success(f"Created {safe} in {base.name}.", path=str(target), created=True)


@registry.tool(
    "read_file_metadata",
    "Read a file's size, type and timestamps without opening it.",
    {"path": {"type": "string", "description": "Full path to the file", "required": True}},
    category="files",
)
def read_file_metadata(path: str) -> ToolResult:
    target = resolve_path(path)
    if not target.exists():
        return ToolResult.fail(f"I couldn't find {target}.")
    st = target.stat()
    data = {
        "path": str(target),
        "name": target.name,
        "type": "folder" if target.is_dir() else (target.suffix.lstrip(".") or "file"),
        "size_kb": round(st.st_size / 1024, 1),
        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "created": datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M"),
    }
    return ToolResult.success(
        f"{target.name} is {data['size_kb']} KB, last modified {data['modified']}.", **data
    )


@registry.tool(
    "rename_file",
    "Rename a file or folder.",
    {"path": {"type": "string", "description": "Current full path", "required": True},
     "new_name": {"type": "string", "description": "New name (without folder path)", "required": True}},
    category="files",
)
def rename_file(path: str, new_name: str) -> ToolResult:
    src = resolve_path(path)
    if not src.exists():
        return ToolResult.fail(f"I couldn't find {src}.")
    safe = "".join(c for c in new_name if c not in '<>:"/\\|?*').strip()
    if not safe:
        return ToolResult.fail("That name isn't valid.")
    if src.is_file() and "." not in safe and src.suffix:
        safe += src.suffix  # keep the extension if the user omitted it
    dst = src.parent / safe
    if dst.exists():
        return ToolResult.fail(f"{safe} already exists in that folder.")
    try:
        src.rename(dst)
    except OSError as e:
        return ToolResult.fail(f"I couldn't rename it: {e}")
    if not dst.exists():
        return ToolResult.fail("The rename could not be verified.")
    return ToolResult.success(f"Renamed to {safe}.", path=str(dst), old_path=str(src))


def _prepare_move(source: str, destination: str) -> tuple[Path, Path] | ToolResult:
    src = resolve_path(source)
    if not src.exists():
        return ToolResult.fail(f"I couldn't find {src}.")
    dst_dir = resolve_path(destination)
    if dst_dir.exists() and dst_dir.is_file():
        return ToolResult.fail(f"{dst_dir} is a file, not a folder.")
    if not dst_dir.exists():
        try:
            dst_dir.mkdir(parents=True)
        except OSError as e:
            return ToolResult.fail(f"I couldn't create the destination folder: {e}")
    return src, dst_dir


@registry.tool(
    "move_file",
    "Move a file or folder into another folder.",
    {"source": {"type": "string", "description": "Full path of the file to move", "required": True},
     "destination": {"type": "string", "description": "Destination folder", "required": True}},
    category="files",
)
def move_file(source: str, destination: str) -> ToolResult:
    prepared = _prepare_move(source, destination)
    if isinstance(prepared, ToolResult):
        return prepared
    src, dst_dir = prepared
    target = dst_dir / src.name
    if target.exists():
        stem, suffix = src.stem, src.suffix
        target = dst_dir / f"{stem}_{int(time.time())}{suffix}"
    try:
        shutil.move(str(src), str(target))
    except (OSError, shutil.Error) as e:
        return ToolResult.fail(f"I couldn't move {src.name}: {e}")
    if not target.exists():
        return ToolResult.fail("The move could not be verified.")
    return ToolResult.success(f"Moved {src.name} to {dst_dir.name}.", path=str(target), source=str(src))


@registry.tool(
    "copy_file",
    "Copy a file or folder into another folder.",
    {"source": {"type": "string", "description": "Full path of the file to copy", "required": True},
     "destination": {"type": "string", "description": "Destination folder", "required": True}},
    category="files",
)
def copy_file(source: str, destination: str) -> ToolResult:
    prepared = _prepare_move(source, destination)
    if isinstance(prepared, ToolResult):
        return prepared
    src, dst_dir = prepared
    target = dst_dir / src.name
    if target.exists():
        target = dst_dir / f"{src.stem}_copy{src.suffix}"
    try:
        if src.is_dir():
            shutil.copytree(str(src), str(target))
        else:
            shutil.copy2(str(src), str(target))
    except (OSError, shutil.Error) as e:
        return ToolResult.fail(f"I couldn't copy {src.name}: {e}")
    if not target.exists():
        return ToolResult.fail("The copy could not be verified.")
    return ToolResult.success(f"Copied {src.name} to {dst_dir.name}.", path=str(target))


@registry.tool(
    "delete_file",
    "Delete files or folders. Sends them to the Recycle Bin when possible. Always requires confirmation.",
    {"paths": {"type": "array", "description": "Full paths to delete", "items": {"type": "string"}, "required": True},
     "permanent": {"type": "boolean", "description": "Bypass the Recycle Bin", "default": False}},
    category="files",
)
def delete_file(paths: list[str], permanent: bool = False) -> ToolResult:
    from ..safety import is_protected_path

    # Check the path as given *and* as resolved: a Windows path handed to a
    # POSIX host would otherwise be rewritten into something that looks safe.
    protected = [p for p in paths if is_protected_path(p) or is_protected_path(resolve_path(p))]
    if protected:
        return ToolResult.fail(f"I won't delete {protected[0]} - it's a protected system location.")
    targets = [resolve_path(p) for p in paths]
    missing = [str(t) for t in targets if not t.exists()]
    existing = [t for t in targets if t.exists()]
    if not existing:
        return ToolResult.fail("None of those files exist.", missing=missing)

    recycled = False
    if not permanent:
        try:
            from send2trash import send2trash  # type: ignore

            for t in existing:
                send2trash(str(t))
            recycled = True
        except Exception:
            recycled = False

    deleted: list[str] = []
    errors: list[str] = []
    if recycled:
        deleted = [str(t) for t in existing]
    else:
        for t in existing:
            try:
                if t.is_dir():
                    shutil.rmtree(t)
                else:
                    t.unlink()
                deleted.append(str(t))
            except OSError as e:
                errors.append(f"{t.name}: {e}")

    still_there = [d for d in deleted if Path(d).exists()]
    if still_there:
        return ToolResult.fail(f"{len(still_there)} items could not be deleted.", failed=still_there)
    where = "the Recycle Bin" if recycled else "permanently deleted"
    msg = f"Deleted {len(deleted)} item{'s' if len(deleted) != 1 else ''}" + (
        f" to {where}." if recycled else "."
    )
    if errors:
        return ToolResult(False, msg + f" {len(errors)} failed.", {"deleted": deleted, "errors": errors})
    return ToolResult.success(msg, deleted=deleted, recycled=recycled, missing=missing)


@registry.tool(
    "list_folder",
    "List the contents of a folder.",
    {"path": {"type": "string", "description": "Folder to list", "required": True},
     "limit": {"type": "integer", "description": "Maximum entries", "default": 50}},
    category="files",
)
def list_folder(path: str, limit: int = 50) -> ToolResult:
    target = resolve_path(path)
    if not target.exists() or not target.is_dir():
        return ToolResult.fail(f"{target} is not a folder.")
    entries = []
    try:
        for e in sorted(target.iterdir())[:limit]:
            entries.append({"name": e.name, "is_folder": e.is_dir(), "path": str(e)})
    except OSError as e:
        return ToolResult.fail(f"I couldn't read that folder: {e}")
    return ToolResult.success(f"{target.name} contains {len(entries)} items.", entries=entries)
