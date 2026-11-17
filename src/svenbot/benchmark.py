"""Honest, reproducible-ish local inference timing without retaining prompt text.

This measures end-to-end wall time in the Svenbot process, not model quality,
energy, or isolated inference time. Hardware/model details must be supplied by
operators when comparing systems; warmup and caching can materially change scores.
"""
from __future__ import annotations

import json
import math
import os
import platform
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .engine import Engine
from .providers import BackendError

MAX_PROMPTS = 1000
MAX_PROMPT_CHARS = 32_000


def load_prompts(path: str | Path) -> list[dict[str, str]]:
    """Load an explicit, bounded JSONL fixture. IDs and categories are metadata."""
    prompts: list[dict[str, str]] = []
    ids: set[str] = set()
    with Path(path).expanduser().open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if len(prompts) >= MAX_PROMPTS:
                raise ValueError(f"At most {MAX_PROMPTS} benchmark prompts are accepted")
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {number}") from exc
            if not isinstance(item, dict) or not isinstance(item.get("prompt"), str):
                raise ValueError(f"Line {number} must have a string 'prompt'")
            prompt = item["prompt"].strip()
            if not prompt or len(prompt) > MAX_PROMPT_CHARS:
                raise ValueError(f"Line {number} has an empty or oversized prompt")
            identifier = item.get("id", str(number))
            category = item.get("category", "uncategorized")
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 80:
                raise ValueError(f"Line {number} needs an id of 1–80 characters")
            if not isinstance(category, str) or not 1 <= len(category) <= 80:
                raise ValueError(f"Line {number} needs a category of 1–80 characters")
            if identifier in ids:
                raise ValueError(f"Duplicate benchmark id: {identifier}")
            ids.add(identifier)
            prompts.append({"id": identifier, "category": category, "prompt": prompt})
    if not prompts:
        raise ValueError("Benchmark fixture must contain at least one prompt")
    return prompts


def _summary(times: list[float]) -> dict:
    data = sorted(times)
    return {
        "samples": len(data),
        "median_ms": round(statistics.median(data), 3),
        "p95_ms": round(data[math.ceil(0.95 * len(data)) - 1], 3),
        "min_ms": round(data[0], 3),
        "max_ms": round(data[-1], 3),
    }


def _process_rss_kib() -> int | None:
    # A high-water mark for *this* Python process; excludes external Ollama/llama.cpp.
    if os.name != "posix":
        return None
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss / 1024) if sys.platform == "darwin" else int(rss)
    except (ImportError, OSError):
        return None


def run_benchmark(engine: Engine, prompts: list[dict[str, str]], *,
                  runs: int = 3, warmup: int = 1) -> dict:
    if not 1 <= runs <= 100 or not 0 <= warmup <= 20:
        raise ValueError("Runs must be 1–100 and warmup 0–20")
    if engine.settings.session:
        raise ValueError("Benchmarks cannot use persisted sessions")
    # Explicit warmup is never counted or included as a measurement.
    warmup_error = None
    for _ in range(warmup):
        engine.reset()
        try:
            engine.ask(prompts[0]["prompt"], prior=[])
        except (BackendError, ValueError, RuntimeError) as exc:
            warmup_error = type(exc).__name__
            break

    rows: list[dict] = []
    groups: dict[str, list[float]] = defaultdict(list)
    for _ in range(runs):
        for item in prompts:
            engine.reset()  # fresh conversation, including PyBot rule memory
            start = time.perf_counter_ns()
            try:
                answer = engine.ask(item["prompt"], prior=[])
                latency_ms = (time.perf_counter_ns() - start) / 1_000_000
                groups[answer.backend].append(latency_ms)
                rows.append({"id": item["id"], "category": item["category"],
                             "backend": answer.backend, "status": "ok",
                             "latency_ms": round(latency_ms, 3)})
            except (BackendError, ValueError, RuntimeError) as exc:
                rows.append({"id": item["id"], "category": item["category"],
                             "backend": None, "status": "error", "error_type": type(exc).__name__})

    report = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": platform.python_version(), "system": platform.system(),
                        "machine": platform.machine(), "cpu_count": os.cpu_count(),
                        "process_peak_rss_kib": _process_rss_kib()},
        "config": {"requested_backend": engine.settings.backend,
                   "requested_model": engine.settings.model, "runs": runs, "warmup": warmup,
                   "prompt_count": len(prompts), "warmup_error_type": warmup_error},
        "summary_by_backend": {key: _summary(values) for key, values in sorted(groups.items())},
        "successful_samples": sum(len(x) for x in groups.values()),
        "failed_samples": sum(row["status"] == "error" for row in rows),
        "samples": rows,
        "limitations": "Wall time including routing and backend transport; process RSS excludes model server. No quality judgment, tokens/sec, or hardware-normalized inference claim.",
    }
    return report


def save_report(report: dict, path: str | Path):
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement; avoid partial result files if interrupted.
    import tempfile
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                                     prefix=".svenbot-bench-", delete=False) as temp:
        tmp = Path(temp.name)
        try:
            json.dump(report, temp, indent=2)
            temp.write("\n")
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, destination)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if os.name == "posix":
        destination.chmod(0o600)
