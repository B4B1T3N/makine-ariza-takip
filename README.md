# Makine Arıza Takip Sistemi

Üretim tesisleri için **internet bağlantısı gerektirmeyen** masaüstü arıza kayıt ve
bakım takip uygulaması. Operatörler arızayı hızlıca bildirir, bakım ekibi kaydı
işleme alır, yöneticiler makine ve ekip performansını raporlardan izler.

- **Teknoloji:** Python 3.11+ · PyQt6 · SQLite · matplotlib · openpyxl
- **Veritabanı:** Tek dosya SQLite — sunucu kurulumu yok
- **Dağıtım:** Tek `.exe` (PyInstaller), teknik bilgi gerektirmeden çalışır
- **Arayüz:** Tamamen Türkçe

---

## İçindekiler

1. [Hızlı başlangıç](#hızlı-başlangıç)
2. [İlk giriş](#i̇lk-giriş)
3. [Roller ve yetkiler](#roller-ve-yetkiler)
4. [Özellikler](#özellikler)
5. [.exe olarak paketleme](#exe-olarak-paketleme)
6. [Veri konumu ve yedekleme](#veri-konumu-ve-yedekleme)
7. [Proje yapısı](#proje-yapısı)
8. [Veritabanı şeması](#veritabanı-şeması)
9. [Testler](#testler)
10. [Sık karşılaşılan durumlar](#sık-karşılaşılan-durumlar)
11. [İleride eklenebilecekler](#i̇leride-eklenebilecekler)

---

## Hızlı başlangıç

Windows'ta, proje klasöründe:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

> **Not — uzun dosya yolu hatası:** PyQt6, Microsoft Store sürümü Python'un uzun
> `site-packages` yoluna kurulurken Windows'un 260 karakter sınırına takılabilir
> (`OSError: [Errno 2] No such file or directory: ...`). Yukarıdaki gibi proje
> klasöründe bir sanal ortam (`.venv`) kullanmak bu sorunu çözer.

Linux/macOS'ta da aynı komutlar geçerlidir (`source .venv/bin/activate`).

### Demo verisiyle denemek

Gerçek verilerle uğraşmadan uygulamayı görmek için 10 makine, 5 kullanıcı ve
~140 arıza kaydı üretin:

```bat
python tools\seed_demo.py            :: mevcut veritabanına ekler
python tools\seed_demo.py --reset    :: veritabanını sıfırlayıp yeniden kurar
```

Demo kullanıcıları (şifre `1234`): `ahmet`, `zeynep` (operatör) · `mehmet`,
`elif` (teknisyen) · `mudur` (yönetici).

### Gerçek kullanıma geçerken

Demo verisini temizleyip yalnızca `admin` hesabıyla boş bir veritabanı bırakmak
için (mevcut veri önce otomatik yedeklenir):

```bat
python tools\reset_db.py
```

---

## İlk giriş

Uygulama ilk açıldığında varsayılan yönetici hesabı otomatik oluşturulur:

| Kullanıcı adı | Şifre   |
| ------------- | ------- |
| `admin`       | `admin` |

Giriş yaptıktan sonra uygulama sizi uyarır — **Ayarlar → Şifremi Değiştir**
menüsünden şifreyi hemen değiştirin. Ardından **Kullanıcılar** ekranından
personelinizi ekleyin.

---

## Roller ve yetkiler

| Yetki                                   | Operatör | Teknisyen | Yönetici |
| --------------------------------------- | :------: | :-------: | :------: |
| Arıza kaydı açma                        |    ✓     |     ✓     |    ✓     |
| Tüm arıza kayıtlarını görme             |    —     |     ✓     |    ✓     |
| Kendi açtığı kayıtları görme            |    ✓     |     ✓     |    ✓     |
| Durum güncelleme (iş akışı)             |    —     |     ✓     |    ✓     |
| Not ekleme / dosya yükleme              |    ✓     |     ✓     |    ✓     |
| Teknisyen atama                         |    —     |     ✓     |    ✓     |
| Makine envanteri yönetimi               |    —     |     —     |    ✓     |
| Raporlar                                |    —     |     ✓     |    ✓     |
| Kullanıcı ve rol yönetimi               |    —     |     —     |    ✓     |
| Yedekten geri yükleme                   |    —     |     —     |    ✓     |

Operatörler yalnızca **kendi açtıkları** kayıtları görür; ekranlarında rapor ve
envanter yönetimi sekmeleri hiç görünmez.

---

## Özellikler

### Arıza kaydı ve durum takibi

Durum akışı zorunludur; ara adım atlanamaz:

```
Açık → İnceleniyor → Parça/Bekleme → Çözüldü → Kapatıldı
```

- Geçerli geçişler uygulama tarafından denetlenir (örn. *Açık*'tan doğrudan
  *Kapatıldı*'ya geçilemez).
- **Çözüldü** ve **Kapatıldı** durumlarına geçerken açıklama girmek zorunludur.
- Çözülmüş bir kayıt yeniden açılırsa çözüm tarihi sıfırlanır — çözüm süresi
  istatistikleri bozulmaz.
- **Kapatıldı** son durumdur, üzerinde değişiklik yapılamaz.

Her kayıt için tam geçmiş tutulur: kim, ne zaman, hangi durumu değiştirdi, hangi
notu ekledi, kimi atadı, hangi dosyayı yükledi.

**Filtreleme:** kayıt no / başlık / açıklama / makine adında metin araması,
makine, durum, öncelik, tarih aralığı ve "bana atananlar" filtreleri.

**Ekler:** her kayda fotoğraf veya belge yüklenebilir (dosya başına en fazla
20 MB). Dosyalar veri klasöründeki `ekler/` altında saklanır.

### Makine envanteri

Makine adı, seri no (benzersiz), konum/hat, kategori, devreye alma tarihi ve
serbest not alanı. Makine detay ekranında o makinenin **tüm arıza geçmişi**,
toplam/açık kayıt sayısı ve ortalama çözüm süresi görünür.

Makineler silinmez, **pasife alınır** — geçmiş kayıtlar korunur. Üzerinde
kapanmamış arıza olan bir makine pasife alınamaz.

### Bildirimler (uygulama içi)

- Yeni arıza açıldığında → atanan teknisyene, atama yoksa tüm bakım ekibine
- Durum veya öncelik değiştiğinde → kaydı açan operatöre ve atanan teknisyene
- Not eklendiğinde → ilgili taraflara
- Atama yapıldığında → atanan kişiye

Sol menüdeki **Bildirimler** düğmesi okunmamış sayıyı gösterir. E-posta/SMS
gönderimi, uygulama çevrimdışı çalıştığı için kapsam dışıdır
(bkz. [İleride eklenebilecekler](#i̇leride-eklenebilecekler)).

### Dashboard ve raporlar

**Ana sayfa:** açık kayıt sayısı, acil öncelikli kayıtlar, bugün açılan/kapanan,
atanmamış kayıtlar, ortalama çözüm süresi; öncelik ve durum dağılımı grafikleri;
role göre değişen öncelikli kayıt listesi.

**Raporlar ekranı** (teknisyen ve yönetici):

- Tarih aralığı seçimi (son 7/30/90 gün, 6 ay, 1 yıl veya özel aralık)
- Açılan/çözülen arıza trendi — günlük, haftalık veya aylık gruplama
- En çok arızalanan 10 makine
- Makine bazında ortalama / en hızlı / en yavaş çözüm süresi
- Personel iş yükü

**Dışa aktarma:** her liste ve rapor Excel (`.xlsx`) veya CSV olarak kaydedilir.
"Tüm Raporları Excel'e Aktar" tek dosyada ayrı sayfalar üretir. CSV çıktısı
UTF-8 BOM + noktalı virgül ayraçla yazılır; Türkçe Excel'de doğrudan düzgün açılır.

---

## .exe olarak paketleme

```bat
build.bat
```

Betik bağımlılıkları kurar, eski çıktıları temizler ve PyInstaller'ı çalıştırır.
Sonuç: **`dist\MakineArizaTakip.exe`** — yaklaşık 64 MB, tek dosya, Python kurulu
olmayan bilgisayarlarda da çalışır.

Elle çalıştırmak isterseniz:

```bat
pip install -r requirements-dev.txt
pyinstaller MakineArizaTakip.spec --noconfirm --clean
```

Kendi simgenizi kullanmak için `MakineArizaTakip.spec` içindeki `icon=None`
satırını `icon="logo.ico"` olarak değiştirin.

### Kurulum yerine dağıtım

Exe tek dosya olduğu için ayrı bir kuruluma gerek yoktur: dosyayı hedef
bilgisayara kopyalayıp çift tıklamak yeterlidir. İsteğe bağlı olarak Inno Setup
veya benzeri bir araçla Başlat menüsü kısayolu üreten bir installer da
hazırlanabilir.

---

## Veri konumu ve yedekleme

### Veritabanı nerede tutulur?

Sırayla ilk bulunan kullanılır:

1. `MAT_DATA_DIR` ortam değişkeni — **paylaşımlı ağ klasörü** için kullanın
2. Exe'nin yanında `portable.txt` dosyası varsa → yanındaki `data\` klasörü
   (USB bellekten taşınabilir kullanım)
3. Varsayılan: `%APPDATA%\MakineArizaTakip\`

Klasör yapısı:

```
MakineArizaTakip\
├── ariza_takip.db     Veritabanı (tüm kayıtlar)
├── ekler\             Arıza kayıtlarına yüklenen dosyalar
└── yedekler\          Uygulama içinden alınan yedekler
```

Uygulama içinden **Ayarlar → Veri Klasörünü Göster** ile bu klasörü açabilirsiniz.

### Yedek alma

**Ayarlar** menüsünden:

- **Yedek Al** — yalnızca veritabanının `.db` kopyası
- **Tam Yedek Al** — veritabanı + tüm ek dosyaları, tek `.zip` arşivinde
- **Yedekten Geri Yükle** (yalnız yönetici) — mevcut veri otomatik olarak
  yedeklenir, ardından seçilen dosya geri yüklenir ve uygulama kapanır

Yedekleme, uygulama açıkken de tutarlı kopya üreten SQLite `backup` API'sini
kullanır. Geri yüklemede dosyanın geçerli bir uygulama yedeği olduğu doğrulanır.

> **Öneri:** Yedekler klasörünü haftalık olarak harici bir diske veya ağ
> klasörüne kopyalayın.

### Birden fazla bilgisayardan erişim

MVP kapsamı tek bilgisayardır. Küçük ekipler için `MAT_DATA_DIR` değişkenini
paylaşımlı bir ağ klasörüne yönlendirerek aynı veritabanını kullanabilirsiniz:

```bat
setx MAT_DATA_DIR "\\sunucu\paylasim\ArizaTakip"
```

Bu senaryoda aynı anda yazan kullanıcı sayısını sınırlı tutun. Yoğun eşzamanlı
kullanım için ileride yerel bir FastAPI/Flask sunucu katmanı eklenmesi
önerilir — mevcut servis katmanı (`app/services/`) arayüzden bağımsız yazıldığı
için bu geçiş kolaydır.

---

## Proje yapısı

```
makine-ariza-takip/
├── run.py                      Başlatıcı
├── build.bat                   Tek tıkla .exe üretimi
├── MakineArizaTakip.spec       PyInstaller yapılandırması
├── requirements.txt            Çalışma zamanı bağımlılıkları
├── requirements-dev.txt        Geliştirme/paketleme araçları
│
├── app/
│   ├── config.py               Sabitler: roller, durumlar, öncelikler, yollar
│   ├── main.py                 Uygulama giriş noktası
│   │
│   ├── db/
│   │   ├── schema.sql          Veritabanı şeması
│   │   └── database.py         Bağlantı yönetimi, kurulum
│   │
│   ├── services/               İş mantığı (arayüzden bağımsız)
│   │   ├── auth_service.py     Giriş, kullanıcı ve yetki yönetimi
│   │   ├── machine_service.py  Makine envanteri
│   │   ├── fault_service.py    Arıza kayıtları, durum akışı, log, ekler
│   │   ├── notification_service.py
│   │   ├── report_service.py   Rapor ve dashboard sorguları
│   │   └── backup_service.py   Yedekleme / geri yükleme
│   │
│   ├── ui/                     PyQt6 ekranları
│   │   ├── style.py            Renk paleti ve stil sayfası
│   │   ├── login_dialog.py
│   │   ├── main_window.py      Sol menü, sayfa yönlendirme
│   │   ├── dashboard_view.py
│   │   ├── faults_view.py / fault_dialog.py / fault_detail_dialog.py
│   │   ├── machines_view.py / machine_dialog.py / machine_detail_dialog.py
│   │   ├── users_view.py / user_dialog.py
│   │   ├── reports_view.py
│   │   ├── notifications_dialog.py
│   │   └── widgets/            Ortak bileşenler ve grafikler
│   │
│   └── utils/
│       ├── security.py         PBKDF2 şifre saklama
│       ├── helpers.py          Tarih/süre biçimlendirme
│       └── export.py           Excel / CSV dışa aktarma
│
├── tests/                      pytest test paketi
└── tools/seed_demo.py          Demo verisi üretici
```

Mimari not: **arayüz doğrudan SQL çalıştırmaz.** Tüm iş kuralları
`app/services/` altındadır; ekranlar yalnızca servisleri çağırır. Bu sayede
ileride web/mobil bir arayüz eklemek veya servisleri bir API'nin arkasına almak
mümkündür.

---

## Veritabanı şeması

| Tablo           | Amaç                                                          |
| --------------- | ------------------------------------------------------------- |
| `users`         | Kullanıcılar, roller, PBKDF2 şifre özeti, aktiflik            |
| `machines`      | Makine künyesi, konum, kategori, devreye alma, aktiflik       |
| `faults`        | Arıza kayıtları; durum, öncelik, bildiren, atanan, tarihler   |
| `fault_logs`    | Kayıt geçmişi: kim / ne zaman / hangi değişiklik / hangi not  |
| `attachments`   | Kayda yüklenen dosyaların künyesi                             |
| `notifications` | Uygulama içi bildirimler, okundu bilgisi                      |
| `app_meta`      | Şema sürümü ve basit ayarlar                                  |

Şemanın tamamı ve alan açıklamaları için `app/db/schema.sql` dosyasına bakın.

**Veri bütünlüğü:** yabancı anahtarlar etkindir. Arıza kaydı olan bir makine
silinemez (`ON DELETE RESTRICT`); arıza kaydı silinirse geçmişi ve ekleri de
silinir (`ON DELETE CASCADE`); kullanıcı silinirse geçmişteki adı `NULL` olur
ancak kayıt korunur — bu yüzden kullanıcılar silinmez, pasife alınır.

**Şifre saklama:** şifreler düz metin tutulmaz. Kullanıcı başına rastgele salt
ile PBKDF2-HMAC-SHA256 (200.000 tur) özeti saklanır; yalnızca standart kütüphane
kullanıldığı için ek bağımlılık gerekmez.

---

## Testler

```bat
.venv\Scripts\python.exe -m pytest tests -q
```

61 test; kimlik doğrulama ve yetkiler, tam durum akışı ve geçersiz geçişlerin
reddi, kayıt geçmişi, tüm filtreler, makine envanteri koruma kuralları,
bildirimler, rapor sorguları, Excel/CSV çıktısı ve yedekleme/geri yükleme
kapsanır. Her test izole geçici bir veritabanı kullanır, gerçek veriye dokunmaz.

---

## Sık karşılaşılan durumlar

**"Kayıtlı aktif makine yok" uyarısı alıyorum.**
Arıza kaydı açmadan önce yöneticinin **Makine Envanteri**'ne en az bir makine
eklemesi gerekir.

**Bir kaydı yanlışlıkla kapattım.**
Kapatılmış kayıt değiştirilemez. Sorun devam ediyorsa aynı makine için yeni bir
kayıt açın; makine detay ekranında iki kayıt da geçmişte görünür.

**Excel dosyası kaydedilemiyor.**
Aynı isimli dosya Excel'de açıksa yazılamaz. Dosyayı kapatıp tekrar deneyin.

**Şifresini unutan bir kullanıcı var.**
Yönetici, **Kullanıcılar → Düzenle** ekranından yeni şifre belirleyebilir.

**Yönetici şifresi unutuldu.**
Şifreler geri döndürülemez biçimde saklanır. Bu durumda yedekten dönmek veya
veritabanındaki `users` tablosuna doğrudan müdahale etmek gerekir.

---

## İleride eklenebilecekler

Bu sürümün kapsamı dışında bırakılan, mevcut yapıya eklenebilecek özellikler:

- **E-posta/SMS bildirimi** — `notification_service._deliver()` fonksiyonu tek
  genişletme noktasıdır; internet erişimi olan kurulumlarda buraya bir e-posta
  kanalı eklenebilir.
- **Ağ üzerinden çok kullanıcılı erişim** — servis katmanının önüne yerel bir
  FastAPI/Flask katmanı.
- Periyodik bakım planlama ve hatırlatma
- Yedek parça / stok takibi
- Otomatik zamanlanmış yedekleme
- Bulut senkronizasyonu, mobil uygulama, çoklu dil desteği
