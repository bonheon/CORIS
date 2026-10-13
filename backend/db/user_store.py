"""
사용자 · 사용자 메모리(md) 저장소.

지금은 SQLite(backend/data/users.db). SQL 은 :name 바인딩만 써서 cx_Oracle 과 문법이 같다 —
회사 Oracle 로 옮길 때는 _connect() 와 스키마(db/schema_oracle.sql)만 바꾸면 된다.

  users                 사용자 기본 정보 (SSO/사용자 API 에서 받아온 값)
  user_memory           사용자당 md 문서 1개 — 최신본
  user_memory_history   md 가 바뀔 때마다 이전 내용을 남긴다 (감사 · 복원용)
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.getenv("USER_DB_PATH") or Path(__file__).resolve().parent.parent / "data" / "users.db")
SCHEMA = Path(__file__).resolve().parent / "schema_sqlite.sql"
HISTORY_KEEP = int(os.getenv("MEMORY_HISTORY_KEEP", "50"))

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return _conn


def _one(sql: str, params: dict) -> Optional[dict]:
    with _lock:
        row = _connect().execute(sql, params).fetchone()
    return dict(row) if row else None


def _all(sql: str, params: dict) -> list[dict]:
    with _lock:
        return [dict(r) for r in _connect().execute(sql, params).fetchall()]


# ── users ─────────────────────────────────────────────────────

def upsert_user(user_id: str, name: str, dept: str = "", email: str = "", profile: Optional[dict] = None) -> dict:
    p = {"user_id": user_id, "name": name, "dept": dept, "email": email,
         "profile": json.dumps(profile or {}, ensure_ascii=False), "now": _now()}
    with _lock:
        c = _connect()
        c.execute("""
            INSERT INTO users (user_id, name, dept, email, profile_json, created_at, last_seen)
            VALUES (:user_id, :name, :dept, :email, :profile, :now, :now)
            ON CONFLICT(user_id) DO UPDATE SET
              name = :name, dept = :dept, email = :email, profile_json = :profile, last_seen = :now
        """, p)
        c.commit()
    return get_user(user_id)


def get_user(user_id: str) -> Optional[dict]:
    u = _one("SELECT * FROM users WHERE user_id = :user_id", {"user_id": user_id})
    if u:
        u["profile"] = json.loads(u.pop("profile_json") or "{}")
    return u


# ── memory ────────────────────────────────────────────────────

def get_memory(user_id: str) -> Optional[dict]:
    return _one("SELECT * FROM user_memory WHERE user_id = :user_id", {"user_id": user_id})


def save_memory(user_id: str, content: str, source: str) -> dict:
    """최신본을 바꾸고 이전 최신본은 history 로. source: chat | edit | restore"""
    now = _now()
    with _lock:
        c = _connect()
        cur = c.execute("SELECT version FROM user_memory WHERE user_id = :user_id", {"user_id": user_id}).fetchone()
        version = (cur["version"] if cur else 0) + 1
        c.execute("""
            INSERT INTO user_memory (user_id, content, version, updated_at, source)
            VALUES (:user_id, :content, :version, :now, :source)
            ON CONFLICT(user_id) DO UPDATE SET
              content = :content, version = :version, updated_at = :now, source = :source
        """, {"user_id": user_id, "content": content, "version": version, "now": now, "source": source})
        c.execute("""
            INSERT INTO user_memory_history (user_id, version, content, source, created_at)
            VALUES (:user_id, :version, :content, :source, :now)
        """, {"user_id": user_id, "version": version, "content": content, "source": source, "now": now})
        c.execute("""
            DELETE FROM user_memory_history
            WHERE user_id = :user_id AND version <= :version - :keep
        """, {"user_id": user_id, "version": version, "keep": HISTORY_KEEP})
        c.commit()
    return get_memory(user_id)


def delete_memory(user_id: str) -> None:
    with _lock:
        c = _connect()
        c.execute("DELETE FROM user_memory WHERE user_id = :user_id", {"user_id": user_id})
        c.commit()


def memory_history(user_id: str, limit: int = 20) -> list[dict]:
    return _all("""
        SELECT version, source, created_at, LENGTH(content) AS chars FROM user_memory_history
        WHERE user_id = :user_id ORDER BY version DESC LIMIT :limit
    """, {"user_id": user_id, "limit": limit})


def memory_version(user_id: str, version: int) -> Optional[dict]:
    return _one("""
        SELECT version, content, source, created_at FROM user_memory_history
        WHERE user_id = :user_id AND version = :version
    """, {"user_id": user_id, "version": version})
