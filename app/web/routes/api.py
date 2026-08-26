"""Çevrimdışı kuyruğun konuştuğu JSON uç noktaları.

Neden ayrı bir yüzey: sayfa rotaları oturum yoksa giriş ekranına yönlendirir.
Kuyruk bir yönlendirmeyi "başarılı gönderim" sanıp kaydı silerdi, bu yüzden
buradaki uçlar yönlendirmez; 401 döner ve kuyruk kaydı elinde tutar.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import config
from app.services import fault_service, machine_service
from app.services.auth_service import CurrentUser
from app.web import deps

router = APIRouter(prefix="/api")


class YeniAriza(BaseModel):
    """Çevrimdışı kuyruktan gelen arıza kaydı."""

    # İstemci üretir. Bağlantı koptuğu için yanıt alınamaz ve kuyruk tekrar
    # denerse, bu alan sayesinde aynı arıza ikinci kez oluşturulmaz.
    client_uuid: str = Field(min_length=8, max_length=64)
    makine_id: int
    baslik: str = Field(min_length=1, max_length=300)
    aciklama: str = ""
    oncelik: str = config.PRIORITY_MEDIUM
    # Arızanın cihazda yazıldığı an (ISO 8601). Kuyrukta beklerken geçen süre
    # çözüm süresi hesabını bozmasın diye sunucuya ulaşma anından ayrı tutulur.
    olusma_zamani: str | None = None


def _kullanici(request: Request) -> CurrentUser:
    """Oturum kontrolü.

    FastAPI bağımlılıkları gövde doğrulamasından önce çalışır. Bu yüzden
    kimlik kontrolü buraya alındı: oturumsuz bir istek, gövdesi ne olursa
    olsun 401 alır. Aksi halde bozuk gövdeli bir istek 422 döner ve kuyruk
    "kayıt hatalı" sanıp geçerli bir kaydı atardı.
    """
    user = deps.mevcut_kullanici(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Oturum gerekli.")
    return user


def _yazan_kullanici(request: Request, user: CurrentUser = Depends(_kullanici)) -> CurrentUser:
    """Oturum + CSRF başlığı.

    Tarayıcı, başka bir sitenin JSON gövdeli isteğine bu başlığı ekleyemez;
    SameSite çerezinin üstüne ikinci bir katman.
    """
    deps.csrf_dogrula(request, request.headers.get("X-CSRF-Token"))
    return user


def _zaman(deger: str | None) -> datetime | None:
    if not deger:
        return None
    try:
        # Tarayıcının ürettiği "...Z" ekini fromisoformat 3.11'de kabul eder,
        # yine de eski istemciler için güvenceye alıyoruz.
        return datetime.fromisoformat(deger.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/makineler")
def makineler(user: CurrentUser = Depends(_kullanici)):
    """Çevrimdışıyken de form doldurulabilsin diye önbelleğe alınan liste."""
    return [
        {
            "id": m["id"],
            "ad": m["name"],
            "konum": m["location"] or "",
            "seri_no": m["serial_no"] or "",
        }
        for m in machine_service.list_machines()
    ]


@router.post("/arizalar")
def ariza_olustur(gelen: YeniAriza, user: CurrentUser = Depends(_yazan_kullanici)):
    # Aynı kaydın tekrar gönderilip gönderilmediğini yanıtta bildirebilmek
    # için önceden bakıyoruz; create_fault zaten mükerrer kayıt açmaz.
    onceki = fault_service.get_fault_by_client_uuid(gelen.client_uuid)

    try:
        fault_id = fault_service.create_fault(
            machine_id=gelen.makine_id,
            title=gelen.baslik,
            description=gelen.aciklama,
            priority=gelen.oncelik,
            reporter_id=user.id,
            client_uuid=gelen.client_uuid,
            occurred_at=_zaman(gelen.olusma_zamani),
        )
    except fault_service.FaultError as exc:
        # 400: kuyruk bu kaydı tekrar denememeli, veri hatalı.
        return JSONResponse({"hata": str(exc)}, status_code=400)

    return JSONResponse(
        {
            "id": fault_id,
            "yeni": onceki is None,
            "adres": "/arizalar/" + str(fault_id),
        },
        status_code=200 if onceki is not None else 201,
    )
