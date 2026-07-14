"""Regression guard for harden_stdout()'s tier-2 (.buffer rewrap) path.

Imports the REAL evals.run_evals.harden_stdout (a sys.path shim makes that work
whether run directly, via pytest, or in CI); falls back to a reference impl only
if evals isn't importable, so the check is self-proving.

Three properties, each failing LOUDLY if broken:

  1. tier-1 (reconfigure present): stdout reconfigured to utf-8/replace in place.
  2. tier-2 flush-through: after rewrapping .buffer, writes + flush actually reach
     the underlying byte sink, correctly utf-8 encoded (no stranded/lost output).
  3. tier-2 GC-close survival: when the OLD wrapper is dropped and garbage-collected,
     it must NOT close the buffer the NEW wrapper now shares. This is the classic
     TextIOWrapper-closes-its-buffer gotcha; the fix is detaching the old wrapper.

This test caught exactly that GC-close bug in the real code (sink.close_calls=1)
before the detach fix landed -- it is not a check that can only go green.
"""
from __future__ import annotations
import sys, io, gc, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REAL_OUT = sys.stdout          # keep the true console to print our own summary
_REAL_ERR = sys.stderr


def _reference_harden_stdout():
    """Mirrors the 3-tier fallback, INCLUDING the detach fix."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")          # tier 1
        except AttributeError:
            buffer = getattr(stream, "buffer", None)
            if buffer is not None:                                           # tier 2
                new = io.TextIOWrapper(buffer, encoding="utf-8",
                                       errors="replace", line_buffering=True)
                try:
                    stream.detach()      # the fix: old wrapper can't close shared buffer
                except Exception:
                    pass
                setattr(sys, name, new)
            # tier 3: no .buffer (e.g. StringIO) -> no-op; str streams can't UnicodeError
        except Exception:
            pass


try:
    from evals.run_evals import harden_stdout as HARDEN
    HARDEN_SRC = "evals.run_evals.harden_stdout (real code)"
except Exception:
    HARDEN = _reference_harden_stdout
    HARDEN_SRC = "reference implementation (evals.run_evals not importable)"

# Non-ASCII payload, written as an escape so this test file itself stays ASCII
# and passes the source guard it lives beside.
_PAYLOAD = "hello utf \u2705"

# ---- fakes -----------------------------------------------------------------


class Sink(io.BytesIO):
    """Stands in for the raw byte sink. Counts close() attempts but stays open
    so we can inspect what was written even if something tried to close it."""
    def __init__(self):
        super().__init__(); self.close_calls = 0
    def close(self):
        self.close_calls += 1     # do NOT actually close


class ReconfigurableStream:
    """A stdout that supports reconfigure() -> exercises tier 1."""
    def __init__(self): self.enc = self.err = None
    def reconfigure(self, encoding=None, errors=None, **kw):
        self.enc, self.err = encoding, errors
    def write(self, s): return len(s)
    def flush(self): pass


class NoReconfigureStream:
    """A wrapped stdout with .buffer but no reconfigure() -> forces tier 2.
    Owns its buffer and closes it on finalize, unless detached (the real gotcha)."""
    def __init__(self, buffer):
        self.buffer = buffer; self.encoding = "cp1252"; self.errors = "strict"
    def write(self, s):
        self.buffer.write(s.encode(self.encoding, self.errors))
    def flush(self): self.buffer.flush()
    def detach(self):
        b = self.buffer; self.buffer = None; return b
    def __del__(self):
        b = getattr(self, "buffer", None)
        if b is not None:
            b.close()

# ---- checks (return (ok, detail) so __main__ can render a summary) ----------


def check_tier1(harden=HARDEN):
    saved = sys.stdout
    fake = ReconfigurableStream()
    sys.stdout = fake
    try:
        harden()
        ok = (fake.enc == "utf-8" and fake.err == "replace")
        detail = f"reconfigure(encoding={fake.enc!r}, errors={fake.err!r})"
    finally:
        sys.stdout = saved
    return ok, detail


def check_tier2_flushthrough(harden=HARDEN):
    saved = sys.stdout
    sink = Sink()
    fake = NoReconfigureStream(sink)
    sys.stdout = fake
    try:
        harden()
        sys.stdout.write(_PAYLOAD + "\n")     # non-ASCII payload through tier 2
        sys.stdout.flush()
        try: sys.stdout.detach()              # so our restore can't close sink
        except Exception: pass
    finally:
        sys.stdout = saved
    got = sink.getvalue().decode("utf-8")
    ok = _PAYLOAD in got
    return ok, f"sink received {got!r}"


def check_tier2_gc_close(harden=HARDEN, expect_survive=True):
    saved = sys.stdout
    sink = Sink()
    fake = NoReconfigureStream(sink)
    sys.stdout = fake
    try:
        harden()
        sys.stdout.write("x\n"); sys.stdout.flush()
        del fake            # drop the OLD wrapper
        gc.collect()        # ...and finalize it; must not close the shared sink
        survived = (sink.close_calls == 0)
        try: sys.stdout.detach()
        except Exception: pass
    finally:
        sys.stdout = saved
    ok = (survived == expect_survive)
    return ok, f"sink.close_calls={sink.close_calls} (survived={survived})"


# ---- pytest entry points ---------------------------------------------------


def test_tier1_reconfigure_in_place():
    ok, detail = check_tier1()
    assert ok, detail


def test_tier2_flush_through():
    ok, detail = check_tier2_flushthrough()
    assert ok, detail


def test_tier2_gc_close_survival():
    ok, detail = check_tier2_gc_close()
    assert ok, detail


# ---- script entry point ----------------------------------------------------


def main():
    print(f"harden under test: {HARDEN_SRC}", file=_REAL_OUT)
    results = [
        ("tier-1 reconfigure in place", *check_tier1()),
        ("tier-2 flush-through (utf-8)", *check_tier2_flushthrough()),
        ("tier-2 GC-close survival",     *check_tier2_gc_close()),
    ]
    print("-" * 60, file=_REAL_OUT)
    allok = True
    for name, ok, detail in results:
        allok &= ok
        # ascii() so this summary can't itself crash on a cp1252 console -- the
        # detail strings carry the non-ASCII payload we deliberately pushed through.
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {ascii(detail)}", file=_REAL_OUT)
    print("-" * 60, file=_REAL_OUT)
    print(f"  RESULT: {'ALL PASS' if allok else 'FAILURE'}", file=_REAL_OUT)
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
