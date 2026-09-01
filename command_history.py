"""
Recent command history for the desktop agent.
Stores the last N executed (query, command, cwd, outcome) so the LLM can use
references like "that folder" or "the file we created" and keep a train of thought.
"""

from collections import deque
import threading

_MAX_ENTRIES = 20
_entries: deque = deque(maxlen=_MAX_ENTRIES)
_lock = threading.Lock()


def record(
    query: str,
    command: str,
    cwd: str,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
) -> None:
    """Append one completed run to recent history."""
    outcome = ""
    if exit_code != 0:
        outcome = f"exit code {exit_code}"
    elif stderr:
        outcome = "stderr present"
    elif stdout:
        first_line = stdout.strip().split("\n")[0][:80]
        outcome = first_line + ("..." if len(stdout.strip()) > 80 else "")
    else:
        outcome = "ok"
    with _lock:
        _entries.append({
            "query": query,
            "command": command,
            "cwd": cwd,
            "outcome": outcome,
        })


def get_recent(n: int = 10) -> list:
    """Return the last n entries in chronological order (oldest first)."""
    with _lock:
        items = list(_entries)[-n:]
    return items


def format_for_prompt(entries: list) -> str:
    """Format recent entries as a string for the LLM prompt."""
    if not entries:
        return ""
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(f"  {i}. User: {e['query']}")
        lines.append(f"     Command: {e['command']}")
        lines.append(f"     (cwd: {e['cwd']})")
        lines.append(f"     Result: {e['outcome']}")
    return "Recent actions (use for references like \"that folder\", \"the file we created\", or to continue from the last step):\n" + "\n".join(lines)
