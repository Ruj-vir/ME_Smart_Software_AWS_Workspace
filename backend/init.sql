-- ══════════════════════════════════════════════════════
--  ME Smart Database Schema
--  รัน auto เมื่อ postgres container เริ่มครั้งแรก
--  (mount ผ่าน /docker-entrypoint-initdb.d/ ใน docker-compose.yml)
-- ══════════════════════════════════════════════════════

-- ── Users ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(100) UNIQUE NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT        NOT NULL,
    role          VARCHAR(50) NOT NULL DEFAULT 'user',
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Folders ───────────────────────────────────────────
-- parent_id = NULL หมายความว่าเป็น root folder
CREATE TABLE IF NOT EXISTS folders (
    id        UUID        PRIMARY KEY,
    name      VARCHAR(255) NOT NULL,
    parent_id UUID        REFERENCES folders(id) ON DELETE CASCADE
);

-- ── Files ─────────────────────────────────────────────
-- object_name คือ path ของไฟล์ใน MinIO
CREATE TABLE IF NOT EXISTS files (
    id          UUID        PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    folder_id   UUID        REFERENCES folders(id) ON DELETE CASCADE,
    object_name TEXT        NOT NULL,
    size        BIGINT      NOT NULL DEFAULT 0,
    mime_type   VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Inspection Records (QAQC Step > Inspection Report) ──
-- object_name คือ path เต็มของไฟล์เวอร์ชันนั้นใน MinIO/S3 (unique อยู่แล้วในตัว)
CREATE TABLE IF NOT EXISTS inspection_records (
    object_name TEXT        PRIMARY KEY,
    record_by   VARCHAR(255) NOT NULL DEFAULT '',
    result      VARCHAR(50)  NOT NULL DEFAULT '',
    note        TEXT        NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── สร้าง admin user ────────────────────────────────
-- สร้าง user ผ่าน API หลัง service ขึ้นมาแล้ว:
--   POST http://localhost:8000/api/register
--   { "username": "admin", "email": "admin@example.com",
--     "password": "your-password", "role": "admin" }
