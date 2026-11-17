"""Read-only local runtime and installed-model discovery.

No downloads, shell invocation, uploads, telemetry or background probes. An installed
model's on-disk size is NOT its runtime memory requirement or evidence of quality.
"""
from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .providers import BackendError, request_json

MAX_MODELS = 128
MODEL_NAME = re.compile(r"^[\w./:-]{1,160}$", re.ASCII)


@dataclass(frozen=True)
class InstalledModel:
    name: str
    disk_bytes: int | None
    parameter_size: str | None = None
    quantization: str | None = None


def _safe_name(value: object) -> str | None:
    if isinstance(value, str) and MODEL_NAME.fullmatch(value):
        return value
    return None


def parse_ollama_tags(response: dict) -> list[InstalledModel]:
    """Parse, bound, de-duplicate and sanitize untrusted model-server metadata."""
    models = response.get("models")
    if not isinstance(models, list):
        raise BackendError("Ollama returned an invalid local model list")
    if len(models) > MAX_MODELS:
        raise BackendError("Ollama model list is too large")
    parsed: dict[str, InstalledModel] = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        name = _safe_name(item.get("name") or item.get("model"))
        if name is None:
            continue
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 10**15:
            size = None
        details = item.get("details")
        if not isinstance(details, dict):
            details = {}
        def metadata(key: str):
            v = details.get(key)
            return v if isinstance(v, str) and len(v) <= 32 and v.isprintable() else None
        parsed[name] = InstalledModel(name, size, metadata("parameter_size"),
                                      metadata("quantization_level"))
    return sorted(parsed.values(), key=lambda item: (item.disk_bytes is None,
                                                     item.disk_bytes or 0, item.name))


def list_ollama_models(url: str, *, allow_remote: bool = False, timeout: float = 1.5) -> list[InstalledModel]:
    data = request_json(url, "/api/tags", timeout=timeout, allow_remote=allow_remote)
    return parse_ollama_tags(data)


def list_compatible_models(url: str, *, allow_remote: bool = False, timeout: float = 1.5) -> list[str]:
    data = request_json(url, "/v1/models", timeout=timeout, allow_remote=allow_remote)
    models = data.get("data")
    if not isinstance(models, list) or len(models) > MAX_MODELS:
        raise BackendError("Compatible endpoint returned an invalid model list")
    return sorted({_safe_name(m.get("id")) for m in models if isinstance(m, dict)} - {None})


def physical_memory_bytes() -> int | None:
    """Best-effort physical RAM estimate; never infer actual free GPU/CPU headroom."""
    try:
        if sys.platform == "win32":
            import ctypes
            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        elif sys.platform == "darwin":
            # sysctlbyname avoids subprocesses and has no network or filesystem access.
            import ctypes
            libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            size = ctypes.c_size_t(ctypes.sizeof(ctypes.c_uint64))
            value = ctypes.c_uint64()
            if libc.sysctlbyname(b"hw.memsize", ctypes.byref(value), ctypes.byref(size), None, 0) == 0:
                return int(value.value)
        else:
            # sysconf is local and available on most Linux/POSIX systems.
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_size > 0:
                return int(pages * page_size)
    except (AttributeError, OSError, ValueError, OverflowError):
        pass
    return None


def container_memory_limit_bytes() -> int | None:
    """Read known Linux cgroup memory limits, avoiding fake large 'unlimited' values."""
    if sys.platform != "linux":
        return None
    values: list[int] = []
    for filename in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            value = Path(filename).read_text(encoding="ascii").strip()
            if value.isdecimal():
                number = int(value)
                if 0 < number < 1 << 55:
                    values.append(number)
        except (OSError, ValueError, OverflowError):
            continue
    return min(values) if values else None


def memory_budget_bytes() -> int | None:
    physical = physical_memory_bytes()
    container = container_memory_limit_bytes()
    return min([n for n in (physical, container) if n is not None], default=None)


def likely_embedding_only(model: InstalledModel) -> bool:
    """Exclude obvious embedding names from an *advisory* chat candidate list.

    This cannot prove support for chat. `/api/show` capability checks and an actual
    inference smoke test belong in later release gates.
    """
    base = model.name.rsplit("/", 1)[-1].lower()
    return any(token in base for token in ("embed", "bge-", "all-minilm", "e5-", "gte-"))


def recommend_installed(models: list[InstalledModel], budget: int | None = None) -> InstalledModel | None:
    """Conservative advisory: smallest likely chat model by known disk footprint.

    Memory data is observational only; weights, KV cache, quantization, accelerators
    and context length make disk-size-to-RAM comparisons unreliable. A model
    must still be verified on its intended hardware.
    """
    candidates = [m for m in models if not likely_embedding_only(m)]
    return min(candidates, key=lambda m: (m.disk_bytes is None, m.disk_bytes or 0, m.name), default=None)


def survey(ollama_url: str, openai_url: str, *, allow_remote: bool = False,
           timeout: float = 1.5) -> dict:
    """Read-only status snapshot. Errors are summarized without endpoint secrets."""
    installed = []
    compatible = []
    states = {"ollama": "unavailable", "openai": "unavailable"}
    try:
        installed = list_ollama_models(ollama_url, allow_remote=allow_remote, timeout=timeout)
        states["ollama"] = ("ready" if recommend_installed(installed) else
                            "no-chat-candidate" if installed else "no-models")
    except BackendError:
        pass
    try:
        compatible = list_compatible_models(openai_url, allow_remote=allow_remote, timeout=timeout)
        states["openai"] = "ready" if compatible else "no-models"
    except BackendError:
        pass
    budget = memory_budget_bytes()
    pick = recommend_installed(installed, budget)
    return {
        "system": platform.system(), "machine": platform.machine(),
        "memory_budget_bytes": budget,
        "backends": states,
        "ollama_models": [asdict(m) for m in installed],
        "compatible_models": compatible,
        "suggested_ollama_model": pick.name if pick else None,
        "recommendation_basis": "smallest likely chat model by installed disk size; chat capability, runtime memory and quality unverified",
        "privacy": "Read-only queries to configured endpoints; no download or upload",
    }
