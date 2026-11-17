"""Adapter to PyBot's pinned upstream runtime (submodule, not a rewritten copy)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


class RulesUnavailable(RuntimeError):
    pass


def _upstream_root() -> Path | None:
    # editable checkout and source tree both work; wheel users can supply an
    # explicit sibling checkout through SVENBOT_PYBOT_PATH.
    import os
    options = [os.environ.get("SVENBOT_PYBOT_PATH"),
               str(Path(__file__).resolve().parents[2] / "upstream" / "pybot")]
    for option in options:
        if option and (Path(option).expanduser() / "bot" / "runtime.py").is_file():
            return Path(option).expanduser().resolve()
    return None


class RulesEngine:
    def __init__(self):
        root = _upstream_root()
        if root is None:
            raise RulesUnavailable(
                "PyBot rules not installed. Run 'git submodule update --init --recursive' "
                "in a source checkout, or set SVENBOT_PYBOT_PATH to a PyBot checkout."
            )
        # PyBot is imported only when selected: its ~640k lines are slow to load.
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            self.runtime = importlib.import_module("bot.runtime")
        except Exception as exc:
            raise RulesUnavailable(f"PyBot failed to load: {exc}") from exc
        self.memory: dict = {}

    def answer(self, prompt: str) -> str:
        result = self.runtime.turn(prompt, self.memory)
        reply = result.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            raise RulesUnavailable("PyBot returned an empty reply")
        return reply.strip()

    def reset(self) -> None:
        self.memory = {}
