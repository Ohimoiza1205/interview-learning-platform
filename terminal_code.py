#!/usr/bin/env python3
"""A small terminal coding assistant for local projects.

The tool keeps all file and command actions explicit. The model can advise,
summarize, and draft changes; the user chooses which local commands and file
edits to run.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


APP_NAME = "terminal-code"
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
API_URL = "https://api.openai.com/v1/responses"
MAX_FILE_BYTES = 180_000
MAX_CONTEXT_CHARS = 24_000


SYSTEM_PROMPT = """You are a senior coding assistant running in a user's terminal.
Be direct, specific, and practical. Prefer reading existing code before proposing
changes. When drafting edits, use complete file replacements only when asked;
otherwise explain the smallest change clearly. Do not claim to have run commands
or changed files unless the user reports that result from the terminal tool."""


@dataclass
class Session:
    root: Path
    cwd: Path
    model: str
    transcript: list[dict[str, str]] = field(default_factory=list)
    last_read: dict[str, str] = field(default_factory=dict)

    @property
    def api_key(self) -> str | None:
        return os.environ.get("OPENAI_API_KEY")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="A local terminal coding assistant.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Workspace directory. Defaults to the current directory.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model to use. Defaults to OPENAI_MODEL or {DEFAULT_MODEL}.",
    )
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Workspace does not exist: {root}", file=sys.stderr)
        return 2

    session = Session(root=root, cwd=root, model=args.model)
    print_header(session)
    repl(session)
    return 0


def print_header(session: Session) -> None:
    key_state = "set" if session.api_key else "missing"
    print(f"{APP_NAME}  {session.root}")
    print(f"model: {session.model}   OPENAI_API_KEY: {key_state}")
    print("Type /help for commands. Type /quit to exit.")
    print()


def repl(session: Session) -> None:
    while True:
        try:
            raw = input(prompt(session))
        except (EOFError, KeyboardInterrupt):
            print()
            return

        line = raw.strip()
        if not line:
            continue
        if line.startswith("/"):
            should_exit = handle_command(session, line)
            if should_exit:
                return
            continue
        ask_model(session, line)


def prompt(session: Session) -> str:
    rel = "." if session.cwd == session.root else str(session.cwd.relative_to(session.root))
    return f"{rel}> "


def handle_command(session: Session, line: str) -> bool:
    try:
        parts = shlex.split(line, posix=False)
    except ValueError as exc:
        print(f"Could not parse command: {exc}")
        return False

    command = parts[0].lower()
    args = parts[1:]

    try:
        if command in {"/quit", "/exit"}:
            return True
        if command == "/help":
            show_help()
        elif command == "/status":
            show_status(session)
        elif command == "/model":
            change_model(session, args)
        elif command == "/cd":
            change_dir(session, args)
        elif command == "/ls":
            list_dir(session, args)
        elif command == "/tree":
            show_tree(session, args)
        elif command == "/read":
            read_file_command(session, args)
        elif command == "/search":
            search_command(session, args)
        elif command == "/run":
            run_command(session, line)
        elif command == "/save":
            save_command(session, args)
        elif command == "/clear":
            session.transcript.clear()
            print("Conversation cleared.")
        else:
            print(f"Unknown command: {command}")
    except AppError as exc:
        print(exc)
    return False


def show_help() -> None:
    print(
        textwrap.dedent(
            """
            Commands
              /status                 Show workspace, model, and key state
              /model [name]            Show or change the model
              /cd <dir>                Move inside the workspace
              /ls [dir]                List files
              /tree [dir]              Show a compact file tree
              /read <file> [a:b]       Read a file, optionally by 1-based lines
              /search <text> [dir]     Search text in readable files
              /run <command>           Run a shell command after confirmation
              /save <file>             Paste replacement content, preview diff, save
              /clear                   Clear conversation history
              /quit                    Exit

            Chat
              Type normally to ask the model. Recent /read and /search results
              are included as context.
            """
        ).strip()
    )


def show_status(session: Session) -> None:
    key_state = "set" if session.api_key else "missing"
    print(f"workspace: {session.root}")
    print(f"cwd:       {session.cwd}")
    print(f"model:     {session.model}")
    print(f"key:       OPENAI_API_KEY is {key_state}")


def change_model(session: Session, args: list[str]) -> None:
    if not args:
        print(session.model)
        return
    session.model = args[0]
    print(f"Model set to {session.model}.")


def change_dir(session: Session, args: list[str]) -> None:
    if not args:
        session.cwd = session.root
        return
    target = resolve_inside(session, args[0])
    if not target.is_dir():
        raise AppError(f"Not a directory: {target}")
    session.cwd = target


def list_dir(session: Session, args: list[str]) -> None:
    target = resolve_inside(session, args[0]) if args else session.cwd
    if not target.is_dir():
        raise AppError(f"Not a directory: {target}")
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for entry in entries:
        marker = "/" if entry.is_dir() else ""
        print(f"{entry.name}{marker}")


def show_tree(session: Session, args: list[str]) -> None:
    target = resolve_inside(session, args[0]) if args else session.cwd
    if not target.is_dir():
        raise AppError(f"Not a directory: {target}")
    max_items = 180
    count = 0
    for path in walk_visible(target):
        rel = path.relative_to(target)
        depth = len(rel.parts) - 1
        if depth > 3:
            continue
        print(f"{'  ' * depth}{path.name}{'/' if path.is_dir() else ''}")
        count += 1
        if count >= max_items:
            print("...")
            break


def read_file_command(session: Session, args: list[str]) -> None:
    if not args:
        raise AppError("Usage: /read <file> [start:end]")
    path = resolve_inside(session, args[0])
    start, end = parse_range(args[1]) if len(args) > 1 else (None, None)
    text = read_text_file(path)
    lines = text.splitlines()
    if start is not None or end is not None:
        lo = 1 if start is None else max(start, 1)
        hi = len(lines) if end is None else min(end, len(lines))
        selected = lines[lo - 1 : hi]
        offset = lo
    else:
        selected = lines
        offset = 1
    numbered = "\n".join(f"{i:>5}  {line}" for i, line in enumerate(selected, offset))
    print(numbered)
    rel = str(path.relative_to(session.root))
    session.last_read[rel] = clip(numbered, MAX_CONTEXT_CHARS // 2)


def search_command(session: Session, args: list[str]) -> None:
    if not args:
        raise AppError("Usage: /search <text> [dir]")
    needle = args[0]
    target = resolve_inside(session, args[1]) if len(args) > 1 else session.cwd
    if not target.is_dir():
        raise AppError(f"Not a directory: {target}")

    matches: list[str] = []
    lowered = needle.lower()
    for path in walk_visible(target):
        if not path.is_file() or is_binaryish(path):
            continue
        try:
            for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if lowered in line.lower():
                    rel = path.relative_to(session.root)
                    matches.append(f"{rel}:{idx}: {line.strip()}")
                    break
        except (OSError, UnicodeDecodeError):
            continue
        if len(matches) >= 80:
            break

    if not matches:
        print("No matches.")
        return
    output = "\n".join(matches)
    print(output)
    session.last_read[f"search:{needle}"] = clip(output, MAX_CONTEXT_CHARS // 2)


def run_command(session: Session, raw_line: str) -> None:
    command = raw_line[len("/run") :].strip()
    if not command:
        raise AppError("Usage: /run <command>")
    if looks_destructive(command):
        raise AppError("Blocked command. Run destructive operations outside this assistant.")

    print(f"cwd: {session.cwd}")
    confirm = input(f"Run `{command}`? [y/N] ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("Cancelled.")
        return

    completed = subprocess.run(
        command,
        cwd=session.cwd,
        shell=True,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    print(f"exit: {completed.returncode}")
    combined = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if combined:
        session.last_read["last command output"] = clip(combined, MAX_CONTEXT_CHARS // 2)


def save_command(session: Session, args: list[str]) -> None:
    if not args:
        raise AppError("Usage: /save <file>")
    path = resolve_inside(session, args[0])
    print("Paste the complete replacement content. End with a line containing only .")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == ".":
            break
        lines.append(line)

    new_text = "\n".join(lines) + ("\n" if lines else "")
    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    diff = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile=str(path.relative_to(session.root)),
        tofile=str(path.relative_to(session.root)),
        lineterm="",
    )
    preview = "\n".join(diff)
    print(preview if preview else "No changes.")
    if not preview:
        return
    confirm = input("Save this file? [y/N] ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("Cancelled.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    print(f"Saved {path.relative_to(session.root)}.")


def ask_model(session: Session, user_text: str) -> None:
    if not session.api_key:
        print("OPENAI_API_KEY is not set. Set it, then ask again.")
        print('PowerShell: $env:OPENAI_API_KEY="sk-..."')
        return

    context = build_context(session)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "user", "content": f"Workspace context:\n{context}"})
    messages.extend(session.transcript[-12:])
    messages.append({"role": "user", "content": user_text})

    try:
        answer = create_response(session, messages)
    except AppError as exc:
        print(exc)
        return

    print_wrapped(answer)
    session.transcript.append({"role": "user", "content": user_text})
    session.transcript.append({"role": "assistant", "content": answer})


def create_response(session: Session, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": session.model,
        "input": [
            {
                "role": msg["role"],
                "content": [{"type": "input_text", "text": msg["content"]}],
            }
            for msg in messages
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {session.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AppError(f"OpenAI API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AppError(f"Could not reach OpenAI API: {exc.reason}") from exc

    text = extract_output_text(body)
    if not text:
        raise AppError("The API returned no text output.")
    return text


def extract_output_text(body: dict) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    chunks: list[str] = []
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and "text" in content:
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def build_context(session: Session) -> str:
    parts = [f"root: {session.root}", f"cwd: {session.cwd}"]
    if session.last_read:
        parts.append("recent terminal context:")
        for name, content in list(session.last_read.items())[-6:]:
            parts.append(f"\n--- {name} ---\n{content}")
    return clip("\n".join(parts), MAX_CONTEXT_CHARS)


def resolve_inside(session: Session, value: str) -> Path:
    raw = Path(value)
    path = raw if raw.is_absolute() else session.cwd / raw
    resolved = path.resolve()
    try:
        resolved.relative_to(session.root)
    except ValueError as exc:
        raise AppError("Path must stay inside the workspace.") from exc
    return resolved


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise AppError(f"File does not exist: {path}")
    if not path.is_file():
        raise AppError(f"Not a file: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise AppError(f"File is too large for /read: {path}")
    if is_binaryish(path):
        raise AppError(f"File appears to be binary: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AppError(f"Could not read as UTF-8: {path}") from exc


def parse_range(value: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"(\d*)?:(\d*)?", value)
    if not match:
        raise AppError("Range must look like 10:40, 10:, or :40")
    start = int(match.group(1)) if match.group(1) else None
    end = int(match.group(2)) if match.group(2) else None
    return start, end


def walk_visible(root: Path) -> Iterable[Path]:
    skip_dirs = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
    stack = [root]
    while stack:
        current = stack.pop()
        yield current
        if not current.is_dir() or current.name in skip_dirs:
            continue
        try:
            children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            continue
        stack.extend(reversed(children))


def is_binaryish(path: Path) -> bool:
    binary_suffixes = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".exe",
        ".dll",
        ".bin",
        ".pyc",
    }
    return path.suffix.lower() in binary_suffixes


def looks_destructive(command: str) -> bool:
    lowered = command.lower()
    blocked_patterns = [
        r"\brm\s+-",
        r"\bdel\s+",
        r"\brmdir\s+",
        r"\bremove-item\b",
        r"\bgit\s+reset\b",
        r"\bgit\s+clean\b",
        r"\bformat\b",
    ]
    return any(re.search(pattern, lowered) for pattern in blocked_patterns)


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def print_wrapped(text: str) -> None:
    for block in text.split("\n"):
        if not block:
            print()
            continue
        if block.startswith("    ") or block.startswith("\t"):
            print(block)
        else:
            print(textwrap.fill(block, width=96, replace_whitespace=False))


class AppError(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
