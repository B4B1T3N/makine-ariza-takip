# Makine Arıza Takip Sistemi — bulut sürümü

> **Bu `bulut` dalıdır.** Çalışan çevrimdışı masaüstü sürüm `master` dalındadır
> ve bozulmamıştır. Buradaki çalışma, uygulamayı buluta taşıma geçişidir.

Üretim tesisi için arıza kayıt ve bakım takip sistemi. Operatörler arızayı
bildirir, bakım ekibi kaydı işleme alır, yöneticiler makine ve ekip
performansını raporlardan izler.

- **Veritabanı:** PostgreSQL 17 (yerel geliştirmede kurulu, üretimde yönetilen servis)
- **İş mantığı:** Python — arayüzden bağımsız `app/services/` katmanı
- **Arayüz:** şu an PyQt6 masaüstü (Faz 2–3'te web arayüzüne devredilecek)
- **Arayüz dili:** tamamen Türkçe

---

## Geçiş planı ve nerede olduğumuz

| Faz | Kapsam | Durum |
|---|---|---|
| **1** | PostgreSQL'e geçiş, saat dilimi, çevrimdışı senkron şeması, eşzamanlılık | ✅ **Tamamlandı** |
| 2 | FastAPI + oturum, arıza listesi/oluşturma/detay, çevrimdışı kuyruk | Sırada |
| 3 | Makine envanteri, kullanıcılar, dashboard, raporlar (web) | — |
| 4 | Ekleri nesne depolamaya (S3/Blob) taşıma | — |
| 5 | Yayın: HTTPS, ortam değişkenleri, yedek doğrulaması | — |

**Faz 1'in kabul kriteri:** mevcut masaüstü arayüz, tek satır değişmeden
PostgreSQL üzerinde çalışmalı. Sağlandı — veri katmanının doğruluğu web kodu
yazılmadan önce kanıtlandı.

---

## Hızlı başlangıç

### 1. PostgreSQL

Yerel geliştirme için PostgreSQL 17 gerekir:

```bat
winget install --id PostgreSQL.PostgreSQL.17
```

Ardından iki veritabanı oluşturun:

```bat
"C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "CREATE DATABASE ariza_takip"
"C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "CREATE DATABASE ariza_takip_test"
```

### 2. Uygulama

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
:: .env dosyasını açıp DATABASE_URL içindeki şifreyi kendi şifrenizle değiştirin

python run.py
```

### 3. Demo verisi (isteğe bağlı)

```bat
python tools\seed_demo.py --reset
```

10 makine, 5 kullanıcı ve ~140 arıza kaydı üretir. Giriş: `mudur` / `1234`
(diğerleri: `ahmet`, `zeynep` operatör; `mehmet`, `elif` teknisyen).

Gerçek kullanıma geçerken demo veriyi temizlemek için:

```bat
python tools\reset_db.py
```

### İlk giriş

Varsayılan yönetici: **`admin` / `admin`**. Uygulama sizi uyarır —
**Ayarlar → Şifremi Değiştir** menüsünden hemen değiştirin.

> **Uzun dosya yolu hatası (Windows):** PyQt6, Microsoft Store sürümü Python'un
> uzun `site-packages` yoluna kurulurken 260 karakter sınırına takılabilir.
> Proje klasöründe `.venv` kullanmak bunu çözer.

---

## Faz 1'de ne değişti

### Zaman damgaları artık UTC

Tüm zamanlar `TIMESTAMPTZ` olarak **UTC** saklanır, ekranda **Europe/Istanbul**
saatiyle gösterilir. Raporlardaki gün sınırları da yerel saate göre hesaplanır
(`AT TIME ZONE`), yoksa gece yarısı civarındaki kayıtlar yanlış güne düşerdi.

Saat dilimi `MAT_TIMEZONE` ile değiştirilebilir.

### Çevrimdışı kayıt için üç yeni sütun

İnternet kesildiğinde operatörün girdiği kayıt tarayıcıda kuyruğa alınacak ve
bağlantı gelince gönderilecek (Faz 2). Bunun şema tarafı Faz 1'de hazırlandı:

| Sütun | Ne işe yarıyor |
|---|---|
| `faults.client_uuid` | Kaydın kimliğini istemci üretir. Yanıt kaybolup istemci tekrar denerse **aynı arıza ikinci kez kaydedilmez.** |
| `faults.occurred_at` | Arızanın **cihazda yazıldığı** an. `created_at` sunucuya ulaştığı andır. Çevrimdışı kayıtta ikisi saatlerce farklı olabilir. |
| `faults.version` | İyimser kilitleme. İki teknisyen aynı kaydı aynı anda değiştiremez; ikincisi uyarı alır. |

Çözüm süresi ve trend raporları `occurred_at` üzerinden hesaplanır. `created_at`
kullanılsaydı, çevrimdışı bekleyen bir kaydın çözüm süresi olduğundan kısa görünürdü.

**Çevrimdışı kapsamı:** korunan şey operatörün **yeni kayıt girişidir**.
Çevrimdışıyken tüm listeyi görüntüleme ve durum değiştirme kapsam dışıdır —
o çift yönlü senkronizasyon demektir ve ayrı bir çakışma çözümü gerektirir.

### SQL lehçesi çevirisi

`julianday` → `EXTRACT(EPOCH FROM ...)`, `strftime` → `to_char`,
`COLLATE NOCASE` → `CITEXT`, `AUTOINCREMENT` → `IDENTITY`,
`?` → `%s`. Türkçe harf sıralaması için `COLLATE "tr-TR-x-icu"` kullanılır.

### Bağlantı havuzu ve işlem bütünlüğü

`app/db/database.py` artık psycopg3 bağlantı havuzu kullanır. `db.transaction()`
bloğu içindeki tüm sorgular aynı bağlantıya katılır (contextvars ile), böylece
"durum değişikliği + geçmiş kaydı + bildirim" ya birlikte yazılır ya hiç.

---

## Roller ve yetkiler

| Yetki | Operatör | Teknisyen | Yönetici |
| --- | :-: | :-: | :-: |
| Arıza kaydı açma | ✓ | ✓ | ✓ |
| Tüm kayıtları görme | — | ✓ | ✓ |
| Durum güncelleme | — | ✓ | ✓ |
| Not / dosya ekleme | ✓ | ✓ | ✓ |
| Teknisyen atama | — | ✓ | ✓ |
| Makine envanteri yönetimi | — | — | ✓ |
| Raporlar | — | ✓ | ✓ |
| Kullanıcı yönetimi | — | — | ✓ |

Operatörler yalnızca kendi açtıkları kayıtları görür; envanter ve rapor
sekmeleri ekranlarında hiç oluşturulmaz.

---

## Özellikler

**Durum akışı** (ara adım atlanamaz):

```
Açık → İnceleniyor → Parça/Bekleme → Çözüldü → Kapatıldı
```

Çözüldü/Kapatıldı geçişlerinde açıklama zorunludur. Çözülmüş kayıt yeniden
açılırsa çözüm tarihi sıfırlanır. Kapatıldı son durumdur.

Her kayıtta tam geçmiş tutulur: kim, ne zaman, hangi durumu değiştirdi, hangi
notu ekledi, kimi atadı, hangi dosyayı yükledi.

**Filtreleme:** kayıt no / başlık / açıklama / makine adında arama, makine,
durum, öncelik, tarih aralığı, "bana atananlar".

**Makine envanteri:** künye, makine bazlı arıza geçmişi, ortalama çözüm süresi.
Makineler silinmez, pasife alınır; üzerinde açık arıza varsa pasife alınamaz.

**Bildirimler:** uygulama içi. Yeni arıza → bakım ekibine; durum/öncelik
değişikliği ve notlar → kaydı açana ve atanana.

**Raporlar:** arıza trendi (gün/hafta/ay), en çok arızalanan 10 makine, makine
bazında çözüm süreleri, personel iş yükü. Tümü Excel/CSV olarak dışa aktarılır.

---

## Yedekleme

Karar: **haftada bir dış yedek.**

```bat
python tools\backup_now.py           :: periyot dolduysa al
python tools\backup_now.py --force   :: hemen al
python tools\backup_now.py --durum   :: son yedeğin yaşını göster
```

`pg_dump` ile sıkıştırılmış özel biçimde alınır ve **her yedek `pg_restore`
ile doğrulanır** — doğrulanmamış yedek yedek değildir. En yeni 12 yedek
saklanır, eskiler otomatik silinir.

Haftalık zamanlanmış görev (Windows):

```bat
schtasks /create /tn "Ariza Takip Yedek" /sc weekly /d SUN /st 03:00 ^
         /tr "\"%CD%\.venv\Scripts\python.exe\" \"%CD%\tools\backup_now.py\""
```

Sunucuda (Linux) crontab:

```
0 3 * * 0  /opt/ariza-takip/.venv/bin/python /opt/ariza-takip/tools/backup_now.py
```

> **Önemli:** Haftalık, en kötü senaryoda **7 günlük kayıt kaybı** demektir.
> Yönetilen PostgreSQL sağlayıcıları ücretsiz olarak günlük otomatik yedek +
> zaman noktasına dönüş sunar — **onu kapatmayın.** Buradaki haftalık yedek
> onun yerine değil, sağlayıcıdan bağımsız ikinci bir kopya olarak üstünedir.

### Yerel dosyalar nerede

Ek dosyaları ve yedekler `Belgeler\MakineArizaTakip\` altındadır
(`MAT_DATA_DIR` ile değiştirilebilir). Faz 4'te ekler nesne depolamaya taşınacak.

> `%APPDATA%` bilerek kullanılmıyor: Microsoft Store sürümü Python, AppData
> yazmalarını paketin sanal klasörüne yönlendirir. Python yolu "var" görür ama
> `pg_dump` göremez ve yedekleme sessizce kırılır.

---

## Proje yapısı

```
makine-ariza-takip/
├── run.py                      Başlatıcı
├── .env.example                Ortam değişkeni şablonu (.env gitignore'da)
├── requirements.txt
│
├── app/
│   ├── config.py               Sabitler, DATABASE_URL, saat dilimi, yollar
│   ├── main.py                 Giriş noktası
│   │
│   ├── db/
│   │   ├── schema.sql          PostgreSQL şeması
│   │   └── database.py         Bağlantı havuzu, transaction, sorgu yardımcıları
│   │
│   ├── services/               İş mantığı — arayüzden bağımsız, web'e taşınacak
│   │   ├── auth_service.py     Giriş, kullanıcı, yetkiler
│   │   ├── machine_service.py  Makine envanteri
│   │   ├── fault_service.py    Arıza, durum akışı, log, ekler, idempotency
│   │   ├── notification_service.py
│   │   ├── report_service.py   Rapor sorguları
│   │   └── backup_service.py   pg_dump / pg_restore
│   │
│   ├── ui/                     PyQt6 ekranları (Faz 3'te web devralacak)
│   └── utils/
│       ├── security.py         PBKDF2 şifre saklama
│       ├── helpers.py          UTC ↔ yerel saat dönüşümleri
│       └── export.py           Excel / CSV
│
├── tests/                      76 test
└── tools/
    ├── seed_demo.py            Demo verisi
    ├── reset_db.py             Sıfırlama (önce yedek alır)
    └── backup_now.py           Haftalık yedek
```

**Mimari not:** arayüz doğrudan SQL çalıştırmaz. Tüm iş kuralları
`app/services/` altındadır — web arayüzü bu katmanı olduğu gibi kullanacak.

---

## Veritabanı şeması

| Tablo | Amaç |
| --- | --- |
| `users` | Kullanıcılar, roller, PBKDF2 şifre özeti |
| `machines` | Makine künyesi, konum, kategori, aktiflik |
| `faults` | Arıza kayıtları + `client_uuid`, `occurred_at`, `version` |
| `fault_logs` | Kayıt geçmişi: kim / ne zaman / hangi değişiklik |
| `attachments` | Yüklenen dosyaların künyesi |
| `notifications` | Uygulama içi bildirimler |
| `app_meta` | Şema sürümü ve basit ayarlar |

**Veri bütünlüğü:** arıza kaydı olan makine silinemez (`RESTRICT`); arıza
silinirse geçmişi ve ekleri de silinir (`CASCADE`); kullanıcı silinirse
geçmişteki adı `NULL` olur ama kayıt korunur — bu yüzden kullanıcılar
silinmez, pasife alınır.

**Şifreler:** düz metin saklanmaz. Kullanıcı başına rastgele salt ile
PBKDF2-HMAC-SHA256 (200.000 tur). Sadece standart kütüphane kullanılır.

---

## Testler

```bat
.venv\Scripts\python.exe -m pytest tests -q
```

76 test. Her test izole bir test veritabanı kullanır ve şemayı sıfırdan kurar;
`TEST_DATABASE_URL` adında "test" geçmiyorsa çalışmayı reddeder — üretim
veritabanının yanlışlıkla silinmesini önlemek için.

Kapsam: kimlik doğrulama ve yetkiler, tam durum akışı ve geçersiz geçişlerin
reddi, kayıt geçmişi, tüm filtreler, envanter koruma kuralları, bildirimler,
rapor sorguları, Excel/CSV çıktısı, yedekleme/geri yükleme; ayrıca Faz 1'in
yeni davranışları: çevrimdışı idempotency, cihaz saati/sunucu saati ayrımı,
iyimser kilitleme, saat dilimi gün sınırları.

---

## Bilinen kısıtlar

- **Ekler hâlâ yerel diskte.** Faz 4'e kadar sunucuda kalıcı disk gerekir.
- **Oturum yönetimi yok.** `CurrentUser` bellekte bir nesne; web için oturum
  çerezi Faz 2'de gelecek.
- **Şifre karmaşıklık kuralı yok** — sadece en az 4 karakter.
- **Hesap kilitleme yok.** Sınırsız şifre denemesi yapılabilir; PBKDF2'nin
  yavaşlığı kısmi koruma sağlar ama gerçek bir önlem değildir.
- **İnternet kesintisi** — fabrika interneti güvenilir kabul edildi. Çevrimdışı
  koruma yalnızca yeni kayıt girişi içindir (bkz. yukarıdaki kapsam notu).
