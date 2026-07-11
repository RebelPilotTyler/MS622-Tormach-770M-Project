-- CNC Access Manager · SQLite schema + seed data
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS event_logs;
DROP TABLE IF EXISTS access_logs;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT    NOT NULL,
  rfid_hex   TEXT    NOT NULL UNIQUE,
  pin        TEXT    NOT NULL,
  cert_level TEXT    NOT NULL DEFAULT 'none',   -- A / B / none
  status     TEXT    NOT NULL DEFAULT 'active', -- active / disabled
  created_at TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE access_logs (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id   INTEGER REFERENCES users(id),
  login_at  TEXT,
  logout_at TEXT
);

CREATE TABLE event_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER REFERENCES users(id),
  type       TEXT,   -- crash / dull_bit / broken_bit / ok
  note       TEXT,
  created_at TEXT
);

INSERT INTO users (name, rfid_hex, pin, cert_level, status) VALUES
  ('Mason Wang',    'A1B2C3D4', '0770', 'A',    'active'),
  ('Erik Marshall', '0F1E2D3C', '1234', 'A',    'active'),
  ('Test User',     '99887766', '0000', 'B',    'disabled');

INSERT INTO access_logs (user_id, login_at, logout_at) VALUES
  (1, '2026-07-08 14:02', '2026-07-08 14:48'),
  (2, '2026-07-08 15:10', '2026-07-08 16:05'),
  (1, '2026-07-09 09:20', NULL);

INSERT INTO event_logs (user_id, type, note, created_at) VALUES
  (2, 'ok',       'Clean sign-off',           '2026-07-08 16:05'),
  (1, 'dull_bit', '1/4" end mill felt dull',  '2026-07-08 14:48'),
  (3, 'crash',    'Z probe bent — flagged',   '2026-07-07 11:33');
