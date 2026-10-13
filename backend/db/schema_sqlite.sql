-- 사용자 · 사용자 메모리 (SQLite, 로컬 개발용). Oracle 은 schema_oracle.sql
CREATE TABLE IF NOT EXISTS users (
  user_id      TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  dept         TEXT DEFAULT '',
  email        TEXT DEFAULT '',
  profile_json TEXT DEFAULT '{}',
  created_at   TEXT NOT NULL,
  last_seen    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_memory (
  user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
  content    TEXT NOT NULL,          -- 사용자 메모리 markdown
  version    INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  source     TEXT NOT NULL           -- chat | edit | restore
);

CREATE TABLE IF NOT EXISTS user_memory_history (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    TEXT NOT NULL,
  version    INTEGER NOT NULL,
  content    TEXT NOT NULL,
  source     TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_umh_user ON user_memory_history (user_id, version);
