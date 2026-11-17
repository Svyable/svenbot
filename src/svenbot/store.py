"""SQLite conversation storage and explicit, incremental, line-cited local retrieval.

This module never discovers a workspace automatically. Files are ingested only after
an explicit ``svenbot index`` invocation. Everything stored is plaintext; callers
should keep the database on an encrypted disk if their content is sensitive.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path

from .documents import DOCUMENT_EXTENSIONS, MAX_DOCUMENT_BYTES, DocumentError, extract

SAFE_EXTENSIONS = {".md", ".mdx", ".txt", ".rst", ".py", ".go", ".rs", ".js", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml"} | DOCUMENT_EXTENSIONS
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}
SKIP_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
SENSITIVE_NAME = re.compile(r"(?:^|[._-])(secrets?|credentials?|passwords?|tokens?|private|apikey|api_key)(?:[._-]|$)", re.I)
MAX_FILE_BYTES = 1_000_000
MAX_FILES_PER_INDEX = 1000
MAX_CHUNK_CHARS = 1400
OVERLAP_SEGMENTS = 1


def default_db_path() -> Path:
    return Path(os.environ.get("SVENBOT_DB", "~/.local/share/svenbot/svenbot.db")).expanduser()


def workspace_key(workspace: str | Path) -> str:
    return str(Path(workspace).expanduser().resolve())


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    excerpt: str
    end_line: int | None = None
    chunk_id: str = ""


def _chunks(content: str):
    """Yield stable (start line, end line, text, content hash) chunks.

    Long lines are split without losing their source line number; ordinary lines
    are kept whole. Overlap is bounded to one segment, never an entire file.
    """
    segments: list[tuple[int, str]] = []
    for line_no, line in enumerate(content.splitlines(keepends=True), 1):
        for offset in range(0, len(line), MAX_CHUNK_CHARS):
            segments.append((line_no, line[offset:offset + MAX_CHUNK_CHARS]))
    start = 0
    while start < len(segments):
        end = start
        size = 0
        while end < len(segments) and size + len(segments[end][1]) <= MAX_CHUNK_CHARS:
            size += len(segments[end][1])
            end += 1
        # Each segment is <= MAX_CHUNK_CHARS, so at least one is consumed.
        text = "".join(s for _, s in segments[start:end])
        first, last = segments[start][0], segments[end - 1][0]
        digest = hashlib.sha256(f"{first}:{last}\0{text}".encode("utf-8")).hexdigest()
        yield first, last, text, digest
        if end >= len(segments):
            break
        start = max(start + 1, end - OVERLAP_SEGMENTS)


def _raise_walk_error(error: OSError) -> None:
    raise error


def _read_file(path: Path, base: Path, *, strict_document: bool = False) -> str | None:
    """Read only the requested regular file, without following final symlinks.

    Optional non-text parsers never open paths themselves; they receive bounded
    bytes from this descriptor. A corrupt file is skipped in directory batches,
    but explicit document selection returns a helpful error.
    """
    if path.is_symlink() or not path.resolve().is_relative_to(base):
        return None
    document = path.suffix.lower() in DOCUMENT_EXTENSIONS
    limit = MAX_DOCUMENT_BYTES if document else MAX_FILE_BYTES
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                if document and strict_document:
                    raise DocumentError("Document exceeded the 8 MB input limit")
                return None
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                if document and strict_document:
                    raise DocumentError("Document exceeded the 8 MB input limit")
                return None
            if document:
                return extract(path.name, raw)
            return raw.decode("utf-8")
        finally:
            os.close(fd)
    except DocumentError:
        if strict_document:
            raise
        return None
    except (OSError, UnicodeError):
        return None


class Store:
    def __init__(self, db: str | Path):
        self.path = Path(db).expanduser()
        self.ephemeral = str(db) == ":memory:"
        if not self.ephemeral:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(":memory:" if self.ephemeral else str(self.path), timeout=5)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA secure_delete = ON")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY, workspace TEXT NOT NULL, session TEXT NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL)""")
        self.conn.execute("""CREATE INDEX IF NOT EXISTS messages_lookup
          ON messages(workspace, session, id)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS indexed_files (
          workspace TEXT NOT NULL, path TEXT NOT NULL, digest TEXT NOT NULL,
          PRIMARY KEY (workspace, path))""")
        try:
            self.conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks USING fts5(
              workspace UNINDEXED, path UNINDEXED, line_start UNINDEXED,
              line_end UNINDEXED, chunk_id UNINDEXED, content)""")
        except sqlite3.OperationalError as exc:
            raise RuntimeError("SQLite FTS5 support is required for local retrieval") from exc
        self._migrate_legacy_documents()
        self.conn.commit()
        if os.name == "posix" and not self.ephemeral:
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _migrate_legacy_documents(self):
        """Upgrade the v0.1 full-document index without dropping existing data."""
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'").fetchone():
            return
        with self.conn:
            rows = self.conn.execute("SELECT workspace, path, content FROM documents").fetchall()
            for workspace, path, content in rows:
                known = self.conn.execute("SELECT 1 FROM indexed_files WHERE workspace=? AND path=?",
                                          (workspace, path)).fetchone()
                if not known:
                    self._store_content(workspace, path, content)
            # Drop legacy index only after every row is migrated in this transaction.
            self.conn.execute("DROP TABLE documents")

    def _store_content(self, workspace: str, path: str, content: str):
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.conn.execute("DELETE FROM document_chunks WHERE workspace=? AND path=?", (workspace, path))
        self.conn.executemany("""INSERT INTO document_chunks(
            workspace, path, line_start, line_end, chunk_id, content)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [(workspace, path, first, last, hashlib.sha256(f"{path}\0{chunk_digest}".encode()).hexdigest()[:20], fragment)
             for first, last, fragment, chunk_digest in _chunks(content)])
        self.conn.execute("""INSERT INTO indexed_files(workspace, path, digest) VALUES (?, ?, ?)
            ON CONFLICT(workspace, path) DO UPDATE SET digest=excluded.digest""",
                          (workspace, path, digest))

    def close(self):
        self.conn.close()

    def history(self, workspace: str, session: str, limit: int = 16) -> list[dict]:
        rows = self.conn.execute("""SELECT role, content FROM (
            SELECT id, role, content FROM messages WHERE workspace=? AND session=?
            ORDER BY id DESC LIMIT ?) ORDER BY id ASC""", (workspace, session, limit)).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def append_turn(self, workspace: str, session: str, prompt: str, response: str):
        with self.conn:
            self.conn.executemany(
                "INSERT INTO messages(workspace, session, role, content) VALUES (?,?,?,?)",
                [(workspace, session, "user", prompt), (workspace, session, "assistant", response)],
            )

    def clear_session(self, workspace: str, session: str):
        with self.conn:
            self.conn.execute("DELETE FROM messages WHERE workspace=? AND session=?", (workspace, session))

    def clear_workspace(self, workspace: str | Path) -> tuple[int, int]:
        """Explicitly erase this workspace's indexed content and all persisted chats."""
        key = workspace_key(workspace)
        with self.conn:
            files = self.conn.execute("SELECT count(*) FROM indexed_files WHERE workspace=?", (key,)).fetchone()[0]
            messages = self.conn.execute("SELECT count(*) FROM messages WHERE workspace=?", (key,)).fetchone()[0]
            self.conn.execute("DELETE FROM indexed_files WHERE workspace=?", (key,))
            self.conn.execute("DELETE FROM document_chunks WHERE workspace=?", (key,))
            self.conn.execute("DELETE FROM messages WHERE workspace=?", (key,))
        return files, messages

    def add_path(self, source: str | Path, workspace: str | Path) -> tuple[int, int]:
        requested = Path(source).expanduser()
        if requested.is_symlink():
            raise ValueError("Refusing to index an explicitly supplied symlink")
        root = requested.resolve()
        base = Path(workspace).expanduser().resolve()
        if not root.exists():
            raise ValueError(f"No such path: {root}")
        if not (root.is_file() or root.is_dir()):
            raise ValueError("Only ordinary files and directories can be indexed")
        if not root.is_relative_to(base):
            raise ValueError("Indexed content must be inside --workspace")

        def candidate_files():
            if root.is_file():
                yield root
            else:
                for folder, dirs, names in os.walk(root, followlinks=False, onerror=_raise_walk_error):
                    dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
                                     and not (Path(folder) / d).is_symlink())
                    for name in sorted(names):
                        yield Path(folder) / name

        indexed = skipped = visited = 0
        seen: set[str] = set()
        key = str(base)
        # Atomic snapshot: an oversized batch or failed indexing cannot half-prune old data.
        with self.conn:
            for path in candidate_files():
                visited += 1
                if visited > MAX_FILES_PER_INDEX:
                    raise ValueError(f"Limit of {MAX_FILES_PER_INDEX} files per index invocation reached")
                relative_path = path.relative_to(base)
                if (path.is_symlink() or any(part.startswith(".") for part in relative_path.parts)
                        or path.name.lower() in SKIP_NAMES
                        or SENSITIVE_NAME.search(path.name) or path.suffix.lower() not in SAFE_EXTENSIONS):
                    skipped += 1
                    continue
                content = _read_file(path, base, strict_document=root.is_file())
                if content is None:
                    skipped += 1
                    continue
                relative = path.relative_to(base).as_posix()
                seen.add(relative)
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                known = self.conn.execute("SELECT digest FROM indexed_files WHERE workspace=? AND path=?",
                                          (key, relative)).fetchone()
                if known and known[0] == digest:
                    continue
                self._store_content(key, relative, content)
                indexed += 1

            if root.is_file():
                tracked = [root.relative_to(base).as_posix()]
            else:
                # Use POSIX slash as a boundary so 'docs' cannot prune 'docs2'.
                prefix = root.relative_to(base).as_posix()
                rows = self.conn.execute("SELECT path FROM indexed_files WHERE workspace=?", (key,))
                tracked = [p for (p,) in rows if prefix == "." or p.startswith(prefix + "/")]
            for path in tracked:
                if path not in seen:
                    self.conn.execute("DELETE FROM document_chunks WHERE workspace=? AND path=?", (key, path))
                    self.conn.execute("DELETE FROM indexed_files WHERE workspace=? AND path=?", (key, path))
        return indexed, skipped

    def list_files(self, workspace: str | Path, *, limit: int = 500) -> list[dict]:
        """List the selected workspace's indexed documents without revealing content."""
        key = workspace_key(workspace)
        rows = self.conn.execute("""SELECT f.path, f.digest, count(c.chunk_id)
          FROM indexed_files AS f LEFT JOIN document_chunks AS c
            ON c.workspace=f.workspace AND c.path=f.path
          WHERE f.workspace=? GROUP BY f.path, f.digest ORDER BY f.path LIMIT ?""",
          (key, max(1, min(limit, 500)))).fetchall()
        return [{"path": p, "sha256": digest, "chunks": count} for p, digest, count in rows]

    def forget_file(self, workspace: str | Path, path: str) -> bool:
        """Remove exactly one indexed file; never modify the original filesystem."""
        if (not path or path.startswith("/") or "\\" in path or
                any(part in ("", ".", "..") for part in path.split("/"))):
            raise ValueError("Indexed path must be a normalized relative file path")
        key = workspace_key(workspace)
        with self.conn:
            existed = self.conn.execute("SELECT 1 FROM indexed_files WHERE workspace=? AND path=?",
                                        (key, path)).fetchone() is not None
            if existed:
                self.conn.execute("DELETE FROM document_chunks WHERE workspace=? AND path=?", (key, path))
                self.conn.execute("DELETE FROM indexed_files WHERE workspace=? AND path=?", (key, path))
        return existed

    def file_chunks(self, workspace: str | Path, path: str, *, limit: int = 8) -> list[Hit]:
        """Read a bounded initial selection from this file's **indexed snapshot**."""
        rows = self.conn.execute("""SELECT line_start, line_end, content, chunk_id
          FROM document_chunks WHERE workspace=? AND path=? ORDER BY rowid LIMIT ?""",
          (workspace_key(workspace), path, max(1, min(limit, 12)))).fetchall()
        return [Hit(path, int(first), content, int(last), chunk_id)
                for first, last, content, chunk_id in rows]

    def get_chunk(self, workspace: str | Path, path: str, chunk_id: str) -> Hit | None:
        """Look up exact indexed provenance; never read live filesystem contents."""
        rows = self.conn.execute("""SELECT line_start, line_end, content
          FROM document_chunks WHERE workspace=? AND path=? AND chunk_id=? LIMIT 2""",
          (workspace_key(workspace), path, chunk_id)).fetchall()
        if len(rows) != 1:
            return None
        first, last, text = rows[0]
        return Hit(path, int(first), text, int(last), chunk_id)

    def search(self, workspace: str | Path, query: str, limit: int = 4) -> list[Hit]:
        words = list(dict.fromkeys(re.findall(r"[\w]+", query.lower(), flags=re.UNICODE)))[:12]
        words = [word for word in words if len(word) > 1]
        if not words:
            return []
        expr = " OR ".join('"' + word.replace('"', '""') + '"' for word in words)
        rows = self.conn.execute("""SELECT path, line_start, line_end, chunk_id, content
          FROM document_chunks WHERE document_chunks MATCH ? AND workspace=?
          ORDER BY bm25(document_chunks) LIMIT ?""",
          (expr, workspace_key(workspace), max(1, min(limit, 10)))).fetchall()
        return [Hit(path, int(first), content, int(last), chunk_id)
                for path, first, last, chunk_id, content in rows]
