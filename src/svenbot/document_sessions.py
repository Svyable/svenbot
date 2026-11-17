"""Bounded, explicit, ephemeral document slots for the loopback browser UI.

No filesystem writes, cookies, background jobs or unprompted file reads. The
opaque handle is a capability token; anyone with it on the same machine can use
that document until it is cleared or expires. This is not multi-user auth.
"""
from __future__ import annotations

import base64
import binascii
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass

from .documents import DocumentError, extract

MAX_UPLOAD_BYTES = 1_000_000
MAX_EXTRACTED_CHARS = 180_000
MAX_DOCUMENTS = 4
DOCUMENT_TTL_SECONDS = 20 * 60


@dataclass(frozen=True)
class DocumentSlot:
    name: str
    content: str
    expires_at: float


class DocumentVault:
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._documents: dict[str, DocumentSlot] = {}

    def _expire(self):
        now = self._clock()
        for token, slot in list(self._documents.items()):
            if slot.expires_at <= now:
                del self._documents[token]

    @staticmethod
    def _name(filename: object) -> str:
        if (not isinstance(filename, str) or not 1 <= len(filename) <= 120
                or filename.strip() != filename or filename.startswith(".")
                or any(ch in filename for ch in "/\\\x00\r\n")
                or any(unicodedata.category(ch) in ("Cc", "Cf", "Cs") for ch in filename)):
            raise DocumentError("Use a simple document filename without paths or control characters")
        return filename

    def upload(self, filename: object, data: object) -> tuple[str, DocumentSlot]:
        name = self._name(filename)
        if not isinstance(data, str) or not data or len(data) > ((MAX_UPLOAD_BYTES + 2) // 3 * 4):
            raise DocumentError("Document exceeds the 1 MB upload limit or has invalid encoding")
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DocumentError("Invalid base64 document data") from exc
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise DocumentError("Document must be 1 byte to 1 MB")
        # Extraction happens outside the lock: no other client is blocked by a
        # comparatively slow PDF parse. The document parser never follows links.
        content = extract(name, raw)
        if len(content) > MAX_EXTRACTED_CHARS:
            raise DocumentError("Document yields too much text for temporary browser Q&A (180,000 characters)")
        with self._lock:
            self._expire()
            if len(self._documents) >= MAX_DOCUMENTS:
                raise DocumentError("Four temporary documents are already active; clear one or let it expire")
            token = secrets.token_urlsafe(32)
            slot = DocumentSlot(name, content, self._clock() + DOCUMENT_TTL_SECONDS)
            self._documents[token] = slot
            return token, slot

    def get(self, token: object) -> DocumentSlot | None:
        if not isinstance(token, str) or len(token) > 128:
            return None
        with self._lock:
            self._expire()
            return self._documents.get(token)

    def clear(self, token: object) -> bool:
        if not isinstance(token, str):
            return False
        with self._lock:
            self._expire()
            return self._documents.pop(token, None) is not None
