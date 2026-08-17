-- Makine Arıza Takip Sistemi - SQLite şeması
-- Tüm tarih/saat alanları UTC değil, yerel saat ile 'YYYY-MM-DD HH:MM:SS' formatında tutulur.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    salt          TEXT    NOT NULL,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('operator', 'teknisyen', 'yonetici')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS machines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    serial_no       TEXT    UNIQUE COLLATE NOCASE,
    location        TEXT,
    category        TEXT,
    commissioned_at TEXT,
    notes           TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS faults (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id  INTEGER NOT NULL REFERENCES machines(id) ON DELETE RESTRICT,
    title       TEXT    NOT NULL,
    description TEXT,
    priority    TEXT    NOT NULL CHECK (priority IN ('dusuk', 'orta', 'yuksek', 'acil')),
    status      TEXT    NOT NULL CHECK (status IN ('acik', 'inceleniyor', 'beklemede', 'cozuldu', 'kapatildi')),
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assignee_id INTEGER          REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    resolved_at TEXT,
    closed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_faults_machine  ON faults(machine_id);
CREATE INDEX IF NOT EXISTS idx_faults_status   ON faults(status);
CREATE INDEX IF NOT EXISTS idx_faults_reporter ON faults(reporter_id);
CREATE INDEX IF NOT EXISTS idx_faults_assignee ON faults(assignee_id);
CREATE INDEX IF NOT EXISTS idx_faults_created  ON faults(created_at);

-- Her arıza kaydı için değişiklik geçmişi (kim, ne zaman, ne yaptı).
CREATE TABLE IF NOT EXISTS fault_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fault_id   INTEGER NOT NULL REFERENCES faults(id) ON DELETE CASCADE,
    user_id    INTEGER          REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT    NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_logs_fault ON fault_logs(fault_id);

CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fault_id    INTEGER NOT NULL REFERENCES faults(id) ON DELETE CASCADE,
    file_name   TEXT    NOT NULL,
    stored_name TEXT    NOT NULL,
    uploaded_by INTEGER          REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_attachments_fault ON attachments(fault_id);

-- Uygulama içi bildirimler (e-posta/SMS MVP kapsamı dışı).
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fault_id   INTEGER          REFERENCES faults(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    message    TEXT    NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);

-- Şema sürümü / basit anahtar-değer ayarları.
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
