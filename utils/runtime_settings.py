"""Safe persistence helpers for the small set of browser-editable runtime settings."""

from __future__ import annotations

import json
import re
from pathlib import Path


_ASSIGNMENT = re.compile(r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=.*$")


def _encode_dotenv_value(value: str) -> str:
    # JSON double-quoted strings are accepted by python-dotenv and safely keep
    # spaces, #, quotes and backslashes inside tokens.
    return json.dumps(str(value), ensure_ascii=False)


def update_dotenv_file(path: Path, updates: dict[str, str]) -> None:
    """Atomically update selected keys while preserving unrelated .env lines."""
    target = Path(path)
    lines = target.read_text(encoding="utf-8-sig").splitlines() if target.exists() else []
    pending = dict(updates)
    written: set[str] = set()
    output: list[str] = []

    for line in lines:
        match = _ASSIGNMENT.match(line)
        key = match.group("key") if match else ""
        if key in updates:
            if key not in written:
                output.append(f"{match.group('prefix')}{key}={_encode_dotenv_value(updates[key])}")
                written.add(key)
                pending.pop(key, None)
        else:
            output.append(line)

    if pending and output and output[-1].strip():
        output.append("")
    for key, value in pending.items():
        output.append(f"{key}={_encode_dotenv_value(value)}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    temporary.replace(target)
