-- Makine Arıza Takip Sistemi - PostgreSQL şeması
--
-- SQLite sürümünden farkları (bkz. master dalı):
--   * Tüm zaman damgaları TIMESTAMPTZ ve UTC saklanır, görüntülerken çevrilir.
--   * Büyük/küçük harf duyarsız benzersizlik CITEXT ile sağlanır.
--   * faults tablosunda çevrimdışı senkronizasyon ve eşzamanlılık için üç ek
--     sütun vardır: client_uuid, occurred_at, version (aşağıda açıklandı).

CREATE EXTENSION IF NOT EXISTS citext;


CREATE TABLE IF NOT EXISTS users (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      CITEXT      NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    salt          TEXT        NOT NULL,
    full_name     TEXT        NOT NULL,
    role          TEXT        NOT NULL
                  CHECK (role IN ('operator', 'teknisyen', 'yonetici')),
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS machines (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            TEXT        NOT NULL,
    serial_no       CITEXT      UNIQUE,
    location        TEXT,
    category        TEXT,
    commissioned_at DATE,
    notes           TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_machines_active   ON machines(is_active);
CREATE INDEX IF NOT EXISTS idx_machines_category ON machines(category);


CREATE TABLE IF NOT EXISTS faults (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Çevrimdışı kuyruktan gelen kaydın kimliğini istemci üretir. Bağlantı
    -- koptuğu için yanıt alınamaz ve istemci tekrar denerse, bu benzersiz
    -- alan sayesinde sunucu aynı arızayı ikinci kez oluşturmaz.
    client_uuid UUID        NOT NULL UNIQUE DEFAULT gen_random_uuid(),

    machine_id  BIGINT      NOT NULL REFERENCES machines(id) ON DELETE RESTRICT,
    title       TEXT        NOT NULL,
    description TEXT,
    priority    TEXT        NOT NULL
                CHECK (priority IN ('dusuk', 'orta', 'yuksek', 'acil')),
    status      TEXT        NOT NULL
                CHECK (status IN ('acik', 'inceleniyor', 'beklemede',
                                  'cozuldu', 'kapatildi')),
    reporter_id BIGINT      NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assignee_id BIGINT      REFERENCES users(id) ON DELETE SET NULL,

    -- occurred_at: arızanın operatör tarafından yazıldığı an (cihaz saati).
    -- created_at : kaydın sunucuya ulaştığı an.
    -- Çevrimdışı girilen bir kayıtta bu ikisi saatler farklı olabilir.
    -- Raporlar ve çözüm süresi hesapları occurred_at'i kullanır; created_at
    -- yalnızca denetim izi içindir.
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    closed_at   TIMESTAMPTZ,

    -- İyimser kilitleme: her güncellemede artar. İki teknisyen aynı kaydı
    -- aynı anda değiştirmeye çalışırsa ikincisi uyarı alır, sessizce
    -- üzerine yazmaz.
    version     INTEGER     NOT NULL DEFAULT 1,

    -- Kayıt sunucuya ulaşmadan önce doldurulamayacak alanların tutarlılığı.
    CONSTRAINT faults_occurred_before_created
        CHECK (occurred_at <= created_at + INTERVAL '1 minute')
);

CREATE INDEX IF NOT EXISTS idx_faults_machine  ON faults(machine_id);
CREATE INDEX IF NOT EXISTS idx_faults_status   ON faults(status);
CREATE INDEX IF NOT EXISTS idx_faults_reporter ON faults(reporter_id);
CREATE INDEX IF NOT EXISTS idx_faults_assignee ON faults(assignee_id);
CREATE INDEX IF NOT EXISTS idx_faults_occurred ON faults(occurred_at);
-- Açık kayıt listeleri en sık çalışan sorgudur.
CREATE INDEX IF NOT EXISTS idx_faults_active
    ON faults(status, priority) WHERE status IN ('acik', 'inceleniyor', 'beklemede');


-- Her arıza kaydı için değişiklik geçmişi (kim, ne zaman, ne yaptı).
CREATE TABLE IF NOT EXISTS fault_logs (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fault_id   BIGINT      NOT NULL REFERENCES faults(id) ON DELETE CASCADE,
    user_id    BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT        NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_logs_fault ON fault_logs(fault_id, created_at);


CREATE TABLE IF NOT EXISTS attachments (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fault_id    BIGINT      NOT NULL REFERENCES faults(id) ON DELETE CASCADE,
    file_name   TEXT        NOT NULL,
    -- Faz 4'te nesne depolamadaki anahtar olacak; şu an yerel dosya adı.
    stored_name TEXT        NOT NULL,
    uploaded_by BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_attachments_fault ON attachments(fault_id);


-- Uygulama içi bildirimler (e-posta/SMS kapsam dışı).
CREATE TABLE IF NOT EXISTS notifications (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fault_id   BIGINT      REFERENCES faults(id) ON DELETE CASCADE,
    title      TEXT        NOT NULL,
    message    TEXT        NOT NULL,
    is_read    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notifications_unread
    ON notifications(user_id, created_at DESC) WHERE NOT is_read;


-- Şema sürümü / basit anahtar-değer ayarları.
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);


-- Başarısız giriş denemeleri (Faz 5). Hız sınırı buradan hesaplanır.
-- Bellekte tutulmaz: birden fazla uygulama örneği çalıştığında sayaç
-- ortak olmalıdır, yoksa saldırgan örnekler arasında dolaşarak sınırı
-- örnek sayısıyla çarpar.
CREATE TABLE IF NOT EXISTS login_attempts (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Girilen kullanıcı adı (var olmasa bile kaydedilir; aksi halde
    -- "kilitlendi" yanıtı kullanıcının varlığını ele verirdi).
    username   CITEXT      NOT NULL,
    address    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_user
    ON login_attempts(username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_attempts_addr
    ON login_attempts(address, created_at DESC);
