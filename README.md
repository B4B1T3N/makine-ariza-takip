# Makine Arıza Takip Sistemi — bulut sürümü

> **Bu `bulut` dalıdır.** Çalışan çevrimdışı masaüstü sürüm `master` dalındadır
> ve bozulmamıştır. Buradaki çalışma, uygulamayı buluta taşıma geçişidir.

Üretim tesisi için arıza kayıt ve bakım takip sistemi. Operatörler arızayı
bildirir, bakım ekibi kaydı işleme alır, yöneticiler makine ve ekip
performansını raporlardan izler.

- **Veritabanı:** PostgreSQL 17 (yerel geliştirmede kurulu, üretimde yönetilen servis)
- **İş mantığı:** Python — arayüzden bağımsız `app/services/` katmanı
- **Arayüz:** web (FastAPI + Jinja2) — panel, arıza akışı, makine envanteri,
  kullanıcı yönetimi, bildirimler ve raporlar tarayıcıdan çalışır. PyQt6
  masaüstü sürüm aynı veritabanına karşı çalışmaya devam eder; günlük
  kullanım için gereken tek şey değildir
- **Arayüz dili:** tamamen Türkçe

---

## Geçiş planı ve nerede olduğumuz

| Faz | Kapsam | Durum |
|---|---|---|
| **1** | PostgreSQL'e geçiş, saat dilimi, çevrimdışı senkron şeması, eşzamanlılık | ✅ **Tamamlandı** |
| **2** | FastAPI + oturum, arıza listesi/oluşturma/detay, çevrimdışı kuyruk | ✅ **Tamamlandı** |
| **3** | Panel, makine envanteri, kullanıcılar, bildirimler, raporlar (web) | ✅ **Tamamlandı** |
| 4 | Ekleri nesne depolamaya (S3/Blob) taşıma | Sırada |
| 5 | Yayın: HTTPS, ortam değişkenleri, yedek doğrulaması | — |

**Faz 1'in kabul kriteri:** mevcut masaüstü arayüz, tek satır değişmeden
PostgreSQL üzerinde çalışmalı. Sağlandı — veri katmanının doğruluğu web kodu
yazılmadan önce kanıtlandı.

**Faz 2'nin kabul kriteri:** bir operatör tarayıcıdan arıza kaydı açabilmeli,
bir teknisyen kaydı işleme alıp kapatabilmeli ve **bağlantı koptuğunda girilen
kayıt kaybolmamalı.** Sağlandı.

**Faz 3'ün kabul kriteri:** bir yönetici, masaüstü sürüme hiç dönmeden
makine ve kullanıcı yönetebilmeli, raporları görüp Excel'e aktarabilmeli;
her ekran aynı yetki kısıtlarını sorgu düzeyinde korumalı. Sağlandı — geriye
yalnızca ek dosyası **yükleme** kaldı (Faz 4).

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
```

### 3. Web arayüzü

```bat
python web.py
```

Tarayıcıdan `http://127.0.0.1:8000` adresini açın.

Atölyedeki tabletlerin de erişebilmesi için ağa açmak isterseniz:

```bat
python web.py --host 0.0.0.0
```

Geliştirirken kod değiştikçe sunucunun yeniden başlaması için `--gelistirme`
ekleyin. Üretimde başlatıcı yerine doğrudan uvicorn çalıştırılır:

```
uvicorn app.web.main:app --host 0.0.0.0 --port 8000
```

### 4. Masaüstü arayüz (isteğe bağlı)

Faz 3 ile birlikte web arayüzü tüm ekranları kapsar. Masaüstü sürüm aynı
veritabanına karşı çalışmaya devam eder; ek dosyası yüklemek için (Faz 4'e
kadar) hâlâ tek yol odur:

```bat
python run.py
```

### 5. Demo verisi (isteğe bağlı)

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

Varsayılan yönetici: **`admin` / `admin`**. Uygulama sizi uyarır — web
arayüzünde sağ üstteki **Şifre** bağlantısından (masaüstünde **Ayarlar →
Şifremi Değiştir**) hemen değiştirin.

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

İnternet kesildiğinde operatörün girdiği kayıt tarayıcıda kuyruğa alınır ve
bağlantı gelince gönderilir. Şema tarafı Faz 1'de hazırlandı, arayüz tarafı
Faz 2'de bağlandı:

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

## Faz 2'de ne geldi

Web arayüzü **sunucu taraflı** çalışır: sayfa HTML olarak sunucuda üretilir,
tarayıcıya derlenmiş bir uygulama indirilmez. npm ve derleme adımı yoktur;
JavaScript yalnızca çevrimdışı kuyruk için kullanılır. Atölye tabletinde
sayfanın hızlı açılması ve tek dille (Python) bakılabilmesi bu yüzden seçildi.

### Oturum

Oturum, imzalı bir çerezde taşınır ve içinde **yalnızca kullanıcı kimliği**
vardır. Rol ve aktiflik her istekte veritabanından okunur — aksi halde pasife
alınan bir kullanıcı, çerezi geçerli olduğu sürece çalışmaya devam ederdi.

| Önlem | Ne yapar |
|---|---|
| Çerez ömrü 12 saat | Ortak tablette açık kalan oturumu bir vardiyayla sınırlar |
| `SameSite=Lax` | Formun başka bir siteden gönderilmesini engeller |
| Oturum başına CSRF imzası | Formlarda gizli alan, JSON isteklerinde `X-CSRF-Token` başlığı |
| Girişte oturum tazeleme | Giriş öncesi ele geçirilmiş bir çerez giriş sonrası geçersiz olur |
| `devam` adresinin doğrulanması | Giriş sonrası dış siteye yönlendirme (open redirect) kapatıldı |

İmzalama anahtarı `MAT_SECRET_KEY` ile verilir. Verilmezse üretilip
veritabanına yazılır; böylece sunucu yeniden başladığında herkesin oturumu
düşmez ve birden çok uygulama örneği aynı anahtarı paylaşır. **Üretimde
`MAT_SECRET_KEY` tanımlayın** — o zaman anahtar veritabanı yedeklerinin içinde
dolaşmaz.

### Yetkiler sorgunun içinde

Operatörün yalnızca kendi kayıtlarını görmesi, ekranda alan gizleyerek değil
**sorgunun kendisiyle** sağlanır; adres çubuğundan başka bir kaydın numarası
yazılarak aşılamaz. Görme yetkisi olmayan kayıt ile var olmayan kayıt aynı
yanıtı verir, yoksa numara deneyerek hangi kayıtların var olduğu öğrenilebilirdi.

### İyimser kilitleme arayüze bağlandı

Detay sayfası, kaydın `version` değerini gizli alanda taşır. İki teknisyen aynı
kaydı açıp ikisi de değiştirmeye kalkarsa ikincisi *"Bu kayıt siz görüntülerken
başka biri tarafından değiştirildi"* uyarısı alır; sessizce üzerine yazılmaz.
Faz 1'de hazırlanan sütunun karşılığı budur.

### Çevrimdışı kuyruk

Korunan senaryo: **operatör arızayı yazarken bağlantı kopuyor.**

1. Form gönderimi tarayıcıda yakalanır ve `/api/arizalar` uç noktasına gönderilir.
2. Ağ hatası alınırsa kayıt, istemcinin ürettiği `client_uuid` ile birlikte
   tarayıcının IndexedDB deposuna yazılır ve kullanıcıya "kayıt cihazınıza
   alındı" denir.
3. Bağlantı gelince kuyruk otomatik boşaltılır. Sunucu aynı `client_uuid` ile
   ikinci kez çağrılırsa **yeni kayıt açmaz**, mevcut kaydın numarasını döner.
4. Arızanın zamanı, gönderim anı değil **cihazda yazıldığı an**dır. Kayıt
   kuyrukta saatlerce beklese bile çözüm süresi doğru hesaplanır.

`navigator.onLine` bilerek tek ölçüt olarak kullanılmaz: fabrika kablosuzuna
bağlı bir tablet "çevrimiçi" görünür ama sunucuya erişemiyor olabilir. Bu
yüzden gönderim her zaman denenir, kuyruğa düşme kararı gerçek ağ hatasına
bakılarak verilir.

Kuyruğun konuştuğu uçlar oturum yoksa **giriş sayfasına yönlendirmez, 401
döner** — yönlendirme 200 olarak görünür ve kuyruk kaydı gönderilmiş sanıp
silerdi. Aynı nedenle kimlik kontrolü, gövde doğrulamasından önce çalışacak
şekilde bağımlılığa taşındı.

### Service worker

Yalnızca "Yeni Arıza" sayfası ve statik dosyalar önbelleğe alınır. **Arıza
listesi ve detay sayfaları bilerek önbelleğe alınmaz:** bayat bir liste,
teknisyene kaydın gerçek durumunu yanlış gösterir ve bu, sayfanın hiç
açılmamasından daha kötüdür. Ağ yokken diğer sayfalar `/cevrimdisi`
açıklama sayfasına düşer.

> **HTTPS gereği:** service worker ve `crypto.randomUUID` yalnızca güvenli
> bağlamda (HTTPS veya `localhost`) çalışır. Düz `http://` ile LAN'da
> sunulduğunda kuyruk çalışmaya devam eder ama sayfanın kendisi çevrimdışı
> açılmaz. Faz 5'te HTTPS geldiğinde bu kısıt kalkar.

---

## Faz 3'te ne geldi

Web arayüzü artık masaüstü sürümün ekranlarını kapsıyor: panel, makine
envanteri, kullanıcı yönetimi, bildirimler ve raporlar. Servis katmanına
dokunulmadı — eklenen tek iş mantığı, ekranla Excel çıktısının aynı veriyi
kullanmasını sağlayan `report_service.dataset()` oldu.

### Yeni ekranlar

| Adres | Kim görür | Ne yapar |
|---|---|---|
| `/panel` | herkes | Rolüne göre değişen özet; giriş sonrası açılan sayfa |
| `/makineler` | teknisyen, yönetici | Envanter listesi, künye, makine bazlı arıza geçmişi |
| `/makineler/yeni`, `/duzenle`, `/aktiflik` | yönetici | Makine ekleme, künye düzenleme, pasife alma |
| `/kullanicilar` | yönetici | Kullanıcı listesi, ekleme, rol/aktiflik, şifre sıfırlama |
| `/hesap/sifre` | herkes | Kendi şifresini değiştirme |
| `/bildirimler` | herkes | Uygulama içi bildirimler, okundu/temizle |
| `/raporlar` | teknisyen, yönetici | Dört rapor + Excel/CSV indirme |

### Panel operatöre tesis geneli sayı göstermez

Operatörün yetkisi kendi kayıtlarıyla sınırlıdır; panel bu kısıtın etrafından
dolaşan bir yol olmamalıdır. Bu yüzden operatöre **kişisel panel** çıkar:
kendi açık/çözülen kayıt sayıları ve kendi son kayıtları. Tesis geneli özet,
durum dağılımı ve makine sıralaması yalnızca teknisyen ve yöneticide oluşur.
Aynı nedenle envanter ve rapor adresleri operatöre menüde gösterilmemekle
kalmaz, **adres çubuğundan da 403 döner.**

### Grafikler sunucuda üretilir

Durum/öncelik dağılımı ve arıza trendi, genişliği en büyük değere oranlanmış
CSS çubuklarıdır. Grafik kütüphanesi eklenmedi: Faz 2'de verilen "npm ve
derleme adımı yok" kararı sürüyor, sayfa atölye tabletinde hızlı açılıyor.
Renk tek başına anlam taşımaz — her çubuğun yanında sayısı yazılıdır.

### Bildirimin sahibi sorgunun içinde

`notification_service.mark_read()` artık kullanıcı kimliğini de ister.
Masaüstünde bildirim numarası ekrandan geliyordu; web'de adres çubuğundan
gelir ve sahibi olmayan biri başkasının bildirimini okundu yapabilirdi.
Bildirimden arıza kaydına geçişte de yalnızca **kayıt numarası** kabul edilir;
serbest bir adres kabul edilseydi buradan dış siteye yönlendirme yapılabilirdi.

### Ekranla Excel aynı tabloyu kullanır

Rapor sütunları ve satır düzeni `report_service.dataset()` içindedir. Ekranda
gördüğünüz tablo ile indirdiğiniz dosya aynı kaynaktan üretilir; biri
değişince diğeri sessizce farklı kalmaz. Dosya geçici bir adla diske yazılır,
yanıt gönderildikten sonra silinir.

### Web arayüzünde henüz olmayan

| Eksik | Nerede |
|---|---|
| Ek dosyası **yükleme** (görüntüleme ve indirme var) | Faz 4 — dosyalar nesne depolamaya taşınırken |

Ek yüklemek için o zamana kadar masaüstü sürüm kullanılır.

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
├── web.py                      Web sunucusu başlatıcısı  ← Faz 2
├── run.py                      Masaüstü başlatıcı
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
│   ├── web/                    Web arayüzü  ← Faz 2 ve 3
│   │   ├── main.py             FastAPI uygulaması, oturum, hata sayfaları
│   │   ├── deps.py             Oturum, mevcut kullanıcı, yetki, CSRF
│   │   ├── routes/
│   │   │   ├── auth.py         /giris  /cikis
│   │   │   ├── dashboard.py    /panel                           ← Faz 3
│   │   │   ├── faults.py       /arizalar  /arizalar/yeni  /arizalar/{id}
│   │   │   ├── machines.py     /makineler                       ← Faz 3
│   │   │   ├── users.py        /kullanicilar  /hesap/sifre      ← Faz 3
│   │   │   ├── notifications.py  /bildirimler                   ← Faz 3
│   │   │   ├── reports.py      /raporlar  /raporlar/disa-aktar  ← Faz 3
│   │   │   └── api.py          /api/arizalar — çevrimdışı kuyruğun ucu
│   │   ├── templates/          Jinja2 şablonları (Türkçe)
│   │   └── static/
│   │       ├── app.css
│   │       ├── kuyruk.js       IndexedDB çevrimdışı kuyruk
│   │       └── sw.js           Service worker
│   │
│   ├── ui/                     PyQt6 ekranları (web devraldı, kullanımda kalıyor)
│   └── utils/
│       ├── security.py         PBKDF2 şifre saklama
│       ├── helpers.py          UTC ↔ yerel saat dönüşümleri
│       └── export.py           Excel / CSV
│
├── tests/                      141 test
└── tools/
    ├── seed_demo.py            Demo verisi
    ├── reset_db.py             Sıfırlama (önce yedek alır)
    └── backup_now.py           Haftalık yedek
```

**Mimari not:** arayüz doğrudan SQL çalıştırmaz. Tüm iş kuralları
`app/services/` altındadır. Faz 2 bunu doğruladı: web arayüzü servis katmanını
olduğu gibi kullandı, tek eklenen şey liste sayfalaması için `limit`/`offset`
oldu. `app/web/` altında iş kuralı yoktur — yalnızca HTTP taşıması, oturum ve
şablon üretimi.

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

141 test. Her test izole bir test veritabanı kullanır ve şemayı sıfırdan kurar;
`TEST_DATABASE_URL` adında "test" geçmiyorsa çalışmayı reddeder — üretim
veritabanının yanlışlıkla silinmesini önlemek için.

Kapsam: kimlik doğrulama ve yetkiler, tam durum akışı ve geçersiz geçişlerin
reddi, kayıt geçmişi, tüm filtreler, envanter koruma kuralları, bildirimler,
rapor sorguları, Excel/CSV çıktısı, yedekleme/geri yükleme; Faz 1'in
davranışları: çevrimdışı idempotency, cihaz saati/sunucu saati ayrımı,
iyimser kilitleme, saat dilimi gün sınırları.

Faz 2 ile gelen 32 web testi: oturum açma/kapatma, pasife alınan kullanıcının
oturumunun düşmesi, CSRF reddi, dış siteye yönlendirmenin engellenmesi,
operatörün başkasının kaydına adres çubuğundan erişememesi, filtreler ve
sayfalama, rol bazlı işlem yetkileri, eşzamanlı düzenlemenin reddi ve
çevrimdışı kuyruğun sözleri (aynı `client_uuid` ikinci kayıt açmaz, arıza
zamanı gönderim anına kaymaz, oturumsuz istek yönlendirilmeyip 401 alır).

Faz 3 ile gelen 33 web testi: envanterin operatöre kapalı olması ve
teknisyenin görüp değiştirememesi, seri no / kullanıcı adı tekrarının
reddi, açık arızası olan makinenin pasife alınamaması, pasife alınan
makinenin yeni arıza formunda listelenmemesi, yöneticinin kendi hesabını
pasife alamaması, son yöneticinin rolünü düşürememesi, şifre sıfırlama ve
kendi şifresini değiştirme, başkasının bildirimini okundu yapamama,
bildirim hedefinin dış adres kabul etmemesi, operatör panelinde tesis
geneli sayıların ve başkasının kaydının görünmemesi, bozuk/ters tarih
aralığının sayfayı düşürmemesi, Excel ve CSV indirmelerinin doğru dosyayı
üretmesi.

---

## Bilinen kısıtlar

- **Ekler hâlâ yerel diskte.** Faz 4'e kadar sunucuda kalıcı disk gerekir;
  web arayüzünden yükleme de o zaman gelecek.
- **Ek yükleme yalnızca masaüstünde.** Web arayüzü ekleri gösterir ve
  indirir; yükleme Faz 4'te, dosyalar nesne depolamaya taşınırken gelecek.
- **Şifre karmaşıklık kuralı yok** — sadece en az 4 karakter.
- **Hesap kilitleme yok.** Sınırsız şifre denemesi yapılabilir; PBKDF2'nin
  yavaşlığı kısmi koruma sağlar ama gerçek bir önlem değildir. Web arayüzü bu
  yüzeyi internete açtığı için Faz 5'ten önce hız sınırlaması eklenmelidir.
- **HTTPS yok.** Oturum çerezi `https_only=False` ile gönderilir; Faz 5'te
  HTTPS arkasına alınınca `True` yapılmalıdır. Service worker de ancak o zaman
  çalışır (bkz. Faz 2 notu).
- **Çevrimdışı koruma yalnızca yeni kayıt girişi içindir.** Listeyi çevrimdışı
  görüntüleme ve durum değiştirme kapsam dışıdır (bkz. yukarıdaki kapsam notu).
