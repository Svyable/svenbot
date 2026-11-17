"""Offline falsification harness for the evidence selection contract.

Fixtures are synthetic, deliberately adversarial, and cannot measure semantic
truth, retrieval relevance, actual model behavior or novel scientific performance.
They guard against accidentally accepting unsupported nominal quotations.
"""
from __future__ import annotations

import json
from pathlib import Path

from .evidence import validate_selections
from .store import Hit

MAX_CASES = 1000
MAX_BYTES = 2_000_000


def evaluate_contract(path: str | Path) -> dict:
    fixture = Path(path).expanduser()
    if fixture.stat().st_size > MAX_BYTES:
        raise ValueError("Evidence evaluation fixture exceeds 2 MB")
    results = []
    ids = set()
    with fixture.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if len(results) >= MAX_CASES:
                raise ValueError("Evidence evaluation exceeds 1,000 cases")
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON fixture at line {line_no}") from exc
            if (not isinstance(data, dict) or set(data) != {"id", "sources", "response", "expected"}
                    or not isinstance(data["id"], str) or not 1 <= len(data["id"]) <= 80
                    or data["id"] in ids or not isinstance(data["sources"], list)
                    or not 1 <= len(data["sources"]) <= 8
                    or any(not isinstance(x, str) or not 1 <= len(x) <= 1400 for x in data["sources"])
                    or not isinstance(data["response"], str)
                    or type(data["expected"]) is not bool):
                raise ValueError(f"Invalid evidence evaluation case at line {line_no}")
            ids.add(data["id"])
            hits = [Hit(f"fixture/{i}.txt", 1, text, 1, str(i))
                    for i, text in enumerate(data["sources"], 1)]
            try:
                validate_selections(data["response"], hits)
                accepted = True
            except ValueError:
                accepted = False
            results.append({"id": data["id"], "expected": data["expected"],
                            "accepted": accepted, "pass": accepted == data["expected"]})
    if not results:
        raise ValueError("Evidence evaluation fixture must not be empty")
    return {"schema_version": 1, "cases": len(results),
            "passed": sum(row["pass"] for row in results),
            "failed": sum(not row["pass"] for row in results),
            "false_accepts": sum(row["accepted"] and not row["expected"] for row in results),
            "false_rejects": sum(not row["accepted"] and row["expected"] for row in results),
            "results": results,
            "limitations": "Synthetic selection parser tests only; no retrieval/entailment or live model quality score."}
