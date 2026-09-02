"""SQLite upsert store, JSONL export, run log, and the single-run lock."""

from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scrapekit import config
from scrapekit.config import ensure_data_dir

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    target TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    hash TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    changed_at TEXT,
    PRIMARY KEY (target, key)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    started TEXT NOT NULL,
    finished TEXT NOT NULL,
    tier INTEGER NOT NULL,
    urls INTEGER NOT NULL,
    rows INTEGER NOT NULL,
    new INTEGER NOT NULL,
    changed INTEGER NOT NULL,
    errors TEXT NOT NULL,
    output TEXT
);
"""


@dataclass
class RunSummary:
    target: str
    tier: int
    started: str
    finished: str = ""
    urls: int = 0
    rows: int = 0
    new: int = 0
    changed: int = 0
    errors: list[str] = field(default_factory=list)
    output: str = ""
    fill_rates: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> Path:
    return ensure_data_dir() / "scrapekit.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.executescript(SCHEMA_SQL)
    return conn


def _row_hash(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def upsert(target: str, rows: list[dict], key: str | None, conn: sqlite3.Connection | None = None) -> tuple[int, int]:
    """Insert or update rows. Returns (new, changed). Without a key, the row hash is the key."""
    own = conn is None
    conn = conn or connect()
    ts = now_iso()
    new = changed = 0
    try:
        for row in rows:
            k = str(row.get(key)) if key else _row_hash(row)
            if key and row.get(key) in (None, ""):
                continue
            h = _row_hash(row)
            cur = conn.execute("SELECT hash FROM items WHERE target=? AND key=?", (target, k))
            found = cur.fetchone()
            if found is None:
                conn.execute(
                    "INSERT INTO items (target, key, data, hash, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                    (target, k, json.dumps(row, ensure_ascii=False), h, ts, ts),
                )
                new += 1
            elif found[0] != h:
                conn.execute(
                    "UPDATE items SET data=?, hash=?, last_seen=?, changed_at=? WHERE target=? AND key=?",
                    (json.dumps(row, ensure_ascii=False), h, ts, ts, target, k),
                )
                changed += 1
            else:
                conn.execute("UPDATE items SET last_seen=? WHERE target=? AND key=?", (ts, target, k))
        conn.commit()
    finally:
        if own:
            conn.close()
    return new, changed


def write_jsonl(target: str, rows: list[dict]) -> Path:
    d = ensure_data_dir() / target
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def log_run(summary: RunSummary, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            "INSERT INTO runs (target, started, finished, tier, urls, rows, new, changed, errors, output) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (summary.target, summary.started, summary.finished, summary.tier, summary.urls, summary.rows,
             summary.new, summary.changed, json.dumps(summary.errors), summary.output),
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def last_run(target: str) -> dict | None:
    if not db_path().exists():
        return None
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT started, tier, urls, rows, new, changed, errors FROM runs WHERE target=? ORDER BY id DESC LIMIT 1",
            (target,),
        )
        r = cur.fetchone()
    finally:
        conn.close()
    if not r:
        return None
    return {"started": r[0], "tier": r[1], "urls": r[2], "rows": r[3], "new": r[4], "changed": r[5], "errors": json.loads(r[6])}


def item_count(target: str) -> int:
    if not db_path().exists():
        return 0
    conn = connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM items WHERE target=?", (target,)).fetchone()[0]
    finally:
        conn.close()


@contextmanager
def run_lock(wait: bool = True):
    """One `sk run` at a time per data dir. Protects a shared box from stacked crawls."""
    lock_path = ensure_data_dir() / ".run.lock"
    fh = lock_path.open("w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise RuntimeError("another sk run holds the lock; wait or drop --no-wait") from None
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()




def _oneoff_file() -> Path:
    return config.DATA_DIR / "last_oneoff.json"


def remember_oneoff(url: str, tier: int, schema: dict, rates: dict, steps: list[str] | None = None, instruction: str = "") -> None:
    ensure_data_dir()
    _oneoff_file().write_text(json.dumps({"url": url, "tier": tier, "schema": schema, "fill_rates": rates,
                                          "steps": steps or [], "instruction": instruction, "at": now_iso()}, indent=2))


def recall_oneoff() -> dict | None:
    if not _oneoff_file().exists():
        return None
    return json.loads(_oneoff_file().read_text())
