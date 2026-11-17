"""Local SQLite session history and explicit workspace-scoped FTS5 indexing."""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SAFE_EXTENSIONS = {".md", ".mdx", ".txt", ".rst", ".py", ".go", ".rs", ".js", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}
SKIP_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
MAX_FILE_BYTES = 1_000_000
MAX_FILES_PER_INDEX = 1000


def default_db_path() -> Path:
    return Path(os.environ.get("SVENBOT_DB", "~/.local/share/svenbot/svenbot.db")).expanduser()


def workspace_key(workspace: str | Path) -> str:
    return str(Path(workspace).expanduser().resolve())


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    excerpt: str


class Store:
    def __init__(self, db: str | Path):
        self.path = Path(db).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=5)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY, workspace TEXT NOT NULL, session TEXT NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL)""")
        self.conn.execute("""CREATE INDEX IF NOT EXISTS messages_lookup
          ON messages(workspace, session, id)""")
        try:
            self.conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS documents
              USING fts5(workspace UNINDEXED, path UNINDEXED, content)""")
        except sqlite3.OperationalError as exc:
            raise RuntimeError("SQLite FTS5 support is required for local retrieval") from exc
        self.conn.commit()
        # Database is user-only on POSIX; directory already respects umask.
        if os.name == "posix":
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

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

    def add_path(self, source: str | Path, workspace: str | Path) -> tuple[int, int]:
        requested = Path(source).expanduser()
        if requested.is_symlink():
            raise ValueError("Refusing to index an explicitly supplied symlink")
        root = requested.resolve()
        base = Path(workspace).expanduser().resolve()
        if not root.exists():
            raise ValueError(f"No such path: {root}")
        if not root.is_relative_to(base):
            raise ValueError("Indexed content must be inside --workspace")
        def candidate_files():
            if root.is_file():
                yield root
            else:
                for folder, dirs, names in os.walk(root, followlinks=False):
                    dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(folder) / d).is_symlink())
                    for name in sorted(names):
                        yield Path(folder) / name

        indexed = skipped = 0
        for path in candidate_files():
            if indexed >= MAX_FILES_PER_INDEX:
                raise ValueError(f"Limit of {MAX_FILES_PER_INDEX} indexed files per invocation reached")
            if path.is_symlink() or path.name.startswith(".") or path.name.lower() in SKIP_NAMES or path.suffix.lower() not in SAFE_EXTENSIONS:
                skipped += 1
                continue
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                skipped += 1
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                skipped += 1
                continue
            # A path may have changed during indexing; avoid traversing symlinks.
            if not path.resolve().is_relative_to(base):
                skipped += 1
                continue
            relative = str(path.relative_to(base))
            with self.conn:
                self.conn.execute("DELETE FROM documents WHERE workspace=? AND path=?", (str(base), relative))
                self.conn.execute("INSERT INTO documents(workspace, path, content) VALUES (?,?,?)",
                                  (str(base), relative, content))
            indexed += 1
        return indexed, skipped

    def search(self, workspace: str | Path, query: str, limit: int = 4) -> list[Hit]:
        words = list(dict.fromkeys(re.findall(r"[\w]+", query.lower(), flags=re.UNICODE)))[:10]
        words = [word for word in words if len(word) > 1]
        if not words:
            return []
        expr = " OR ".join('"' + word.replace('"', '""') + '"' for word in words)
        rows = self.conn.execute("""SELECT path, content FROM documents
          WHERE documents MATCH ? AND workspace=? ORDER BY rank LIMIT ?""",
          (expr, workspace_key(workspace), max(1, min(limit, 10)))).fetchall()
        results = []
        for path, content in rows:
            lower = content.lower()
            matches = [lower.find(word) for word in words if lower.find(word) >= 0]
            index = min(matches) if matches else 0
            start = max(0, index - 180)
            end = min(len(content), start + 900)
            results.append(Hit(path, content.count("\n", 0, start) + 1, content[start:end]))
        return results
