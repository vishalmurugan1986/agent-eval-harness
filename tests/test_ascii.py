"""Guard: every source file must be pure ASCII.

Why this exists: a non-ASCII glyph in a printed string crashes on Windows
consoles (cp1252) with UnicodeEncodeError -- we hit exactly that with an emoji
in the eval summary. This test turns "pure ASCII" into a standing invariant
instead of a one-time manual check.

Crucially, it fails LOUDLY: nonzero exit if any file carries a non-ASCII byte,
and also nonzero if it somehow scanned zero files (a check that can't detect its
own absence isn't a check). Run it directly (python tests/test_ascii.py) or via
pytest -- both work, no extra dependencies.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ["agent", "evals", "tests"]


def _py_files() -> list[str]:
    found = []
    for d in SCAN_DIRS:
        for dirpath, _, names in os.walk(os.path.join(ROOT, d)):
            if "__pycache__" in dirpath:
                continue
            for n in names:
                if n.endswith(".py"):
                    found.append(os.path.join(dirpath, n))
    return found


def find_non_ascii() -> dict[str, list[tuple[int, int]]]:
    offenders: dict[str, list[tuple[int, int]]] = {}
    for path in _py_files():
        with open(path, "rb") as f:
            data = f.read()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        if bad:
            offenders[os.path.relpath(path, ROOT)] = bad
    return offenders


def test_scanned_some_files() -> None:
    # The absence-is-detectable check: if the globs match nothing, fail rather
    # than silently pass having verified nothing.
    assert _py_files(), f"ASCII guard scanned 0 files under {SCAN_DIRS}"


def test_all_python_files_are_ascii() -> None:
    offenders = find_non_ascii()
    assert not offenders, "Non-ASCII bytes found in: " + ", ".join(
        f"{p} ({len(b)} byte(s), first at offset {b[0][0]}, 0x{b[0][1]:02X})"
        for p, b in offenders.items()
    )


if __name__ == "__main__":
    files = _py_files()
    if not files:
        print(f"ERROR: scanned 0 files under {SCAN_DIRS}", file=sys.stderr)
        raise SystemExit(2)
    offenders = find_non_ascii()
    if offenders:
        for p, bad in offenders.items():
            print(
                f"FAIL {p}: {len(bad)} non-ASCII byte(s), "
                f"first at offset {bad[0][0]} (0x{bad[0][1]:02X})",
                file=sys.stderr,
            )
        raise SystemExit(1)
    print(f"OK: {len(files)} Python files scanned, all pure ASCII")
