"""FastAPI uygulaması: ara katmanlar, hata sayfaları ve yönlendirici bağlama."""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.db import database as db
from app.web import deps
from app.web.routes import (
    api,
    auth,
    dashboard,
    faults,
    machines,
    notifications,
    reports,
    users,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Oturum çerezi ömrü: bir vardiyayı rahatça kapsar, ertesi gün yeniden giriş
# istenir. Ortak kullanılan atölye tabletlerinde açık kalan oturum riskini
# sınırlar.
SESSION_MAX_AGE = 12 * 60 * 60


def _session_secret() -> str:
    """Oturum imzalama anahtarı.

    Öncelik: MAT_SECRET_KEY ortam değişkeni → veritabanındaki kayıtlı anahtar
    → yeni üretilip veritabanına yazılan anahtar.

    Anahtar veritabanında saklandığı için sunucu yeniden başladığında herkesin
    oturumu düşmez ve birden fazla uygulama örneği aynı anahtarı paylaşır.
    Üretimde yine de MAT_SECRET_KEY tercih edilmelidir: o zaman anahtar
    veritabanı yedeklerinin içinde dolaşmaz.
    """
    import os

    env = os.environ.get("MAT_SECRET_KEY")
    if env:
        return env

    row = db.query_one("SELECT value FROM app_meta WHERE key = 'session_secret'")
    if row and row["value"]:
        return row["value"]

    uretilen = secrets.token_urlsafe(48)
    db.execute(
        """INSERT INTO app_meta (key, value) VALUES ('session_secret', %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (uretilen,),
    )
    print(
        "Uyarı: MAT_SECRET_KEY tanımlı değil, oturum anahtarı üretilip "
        "veritabanına yazıldı. Üretimde bu değişkeni tanımlayın."
    )
    return uretilen


def _kurulum_uyarilarini_yaz() -> None:
    """Açılışta kurulum eksiklerini günlüğe yazar.

    Sunucu yine de başlar: yarı yapılandırılmış bir kurulumda uygulamayı
    hiç açmamak, uyarıyı görecek yöneticinin giriş yapmasını da engellerdi.
    """
    from app.services import health_service

    bulgular = health_service.yayin_kontrolleri()
    hatalar, uyarilar = health_service.ozet(bulgular)
    if not bulgular:
        return

    print(f"Kurulum kontrolü: {hatalar} hata, {uyarilar} uyarı")
    for bulgu in bulgular:
        isaret = "HATA " if bulgu["seviye"] == health_service.HATA else "UYARI"
        print(f"  [{isaret}] {bulgu['baslik']}")
    print("  Ayrıntı: python tools/yayin_kontrol.py")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    db.init_db()  # Şema kurulumu idempotenttir.
    _kurulum_uyarilarini_yaz()
    yield
    db.close_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title=config.APP_NAME,
        version=config.APP_VERSION,
        lifespan=_lifespan,
        docs_url=None,      # Bu bir son kullanıcı uygulaması; API gezgini açılmaz.
        redoc_url=None,
        openapi_url=None,
    )

    # Şema henüz kurulmamışsa anahtar okunamaz; kurulumu burada garantiye alıyoruz.
    db.init_db()
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(),
        session_cookie="mat_oturum",
        max_age=SESSION_MAX_AGE,
        same_site="lax",   # Formların başka siteden gönderilmesini engeller.
        # HTTPS arkasında çerez yalnızca güvenli bağlantıda gönderilir.
        # Yerel geliştirmede kapalıdır: açık olsaydı düz HTTP'de çerez hiç
        # gönderilmez ve giriş yapılamazdı.
        https_only=config.https_only(),
    )

    _guvenlik_basliklari(app)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(faults.router)
    app.include_router(machines.router)
    app.include_router(users.router)
    app.include_router(notifications.router)
    app.include_router(reports.router)
    app.include_router(api.router)

    _hata_sayfalari(app)

    @app.get("/", include_in_schema=False)
    def kok():
        return RedirectResponse("/panel", status_code=303)

    @app.get("/saglik", include_in_schema=False)
    def saglik():
        """Bulut sağlayıcısının canlılık kontrolü için."""
        db.scalar("SELECT 1")
        return {"durum": "calisiyor", "surum": config.APP_VERSION}

    # Ağ yokken açılan sayfa. Oturum gerektirmez: service worker bunu kurulum
    # sırasında önbelleğe alır ve bağlantı koptuğunda gösterir.
    @app.get("/cevrimdisi", include_in_schema=False)
    def cevrimdisi(request: Request):
        return deps.sayfa(request, "cevrimdisi.html", {})

    # Service worker'ın kapsamı, sunulduğu klasörle sınırlıdır. /static altından
    # sunulsaydı yalnızca /static/* isteklerini yakalayabilirdi; sayfaları
    # önbelleğe alabilmesi için kökten sunulması gerekir.
    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        from fastapi.responses import FileResponse

        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    return app


def _guvenlik_basliklari(app: FastAPI) -> None:
    """Her yanıta tarayıcı tarafındaki korumaları ekler.

    İçerik güvenliği politikası (CSP) satır içi betiğe izin vermez; bu yüzden
    şablonlardaki `onclick`/`onsubmit` öznitelikleri Faz 5'te
    `static/etkilesim.js` içine taşındı. Satır içi **stile** izin verilir:
    rozet renkleri `style` özniteliğiyle verilir ve bunları sınıflara çevirmek
    politikayı ölçülebilir biçimde güçlendirmezdi.
    """
    csp = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )

    @app.middleware("http")
    async def _basliklar(request: Request, call_next):
        yanit = await call_next(request)
        yanit.headers.setdefault("Content-Security-Policy", csp)
        yanit.headers.setdefault("X-Content-Type-Options", "nosniff")
        yanit.headers.setdefault("X-Frame-Options", "DENY")
        yanit.headers.setdefault("Referrer-Policy", "same-origin")
        # Uygulama kamera/mikrofon/konum istemez; istemediğini söylemek de
        # eklentiler ve gömülü çerçeveler için bir korumadır.
        yanit.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if config.https_only():
            # Yalnızca HTTPS'teyken: düz HTTP'de gönderilen HSTS başlığı
            # tarayıcı tarafından yok sayılır ama yanıltıcı olur.
            yanit.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return yanit


def _hata_sayfalari(app: FastAPI) -> None:
    @app.exception_handler(deps.GirisGerekli)
    async def _giris_gerekli(request: Request, exc: deps.GirisGerekli):
        from urllib.parse import quote

        hedef = "/giris"
        if exc.next_url and exc.next_url != "/":
            hedef += f"?devam={quote(exc.next_url, safe='')}"
        return RedirectResponse(hedef, status_code=303)

    @app.exception_handler(deps.YetkiYok)
    async def _yetki_yok(request: Request, exc: deps.YetkiYok):
        return deps.sayfa(
            request, "hata.html",
            {"baslik": "Yetkiniz yok", "mesaj": exc.mesaj, "kod": 403},
            durum_kodu=403,
        )

    @app.exception_handler(deps.CsrfHatasi)
    async def _csrf(request: Request, exc: deps.CsrfHatasi):
        return deps.sayfa(
            request, "hata.html",
            {
                "baslik": "Form doğrulanamadı",
                "mesaj": "Oturumunuz zaman aşımına uğramış olabilir. "
                         "Sayfayı yenileyip tekrar deneyin.",
                "kod": 400,
            },
            durum_kodu=400,
        )

    @app.exception_handler(404)
    async def _bulunamadi(request: Request, exc):
        if request.url.path.startswith("/api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"hata": "Kayıt bulunamadı."}, status_code=404)
        return deps.sayfa(
            request, "hata.html",
            {
                "baslik": "Sayfa bulunamadı",
                "mesaj": "Aradığınız sayfa taşınmış veya hiç var olmamış olabilir.",
                "kod": 404,
            },
            durum_kodu=404,
        )


app = create_app()
