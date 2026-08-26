#!/usr/bin/env python3
"""Makine Arıza Takip Sistemi - web sunucusu başlatıcısı.

Kullanım:
    python web.py                 :: http://127.0.0.1:8000
    python web.py --host 0.0.0.0  :: ağdaki diğer cihazlara açık
    python web.py --gelistirme    :: dosya değişince otomatik yeniden başlat

Üretimde doğrudan uvicorn çağrılır:
    uvicorn app.web.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    ayristirici = argparse.ArgumentParser(description="Web sunucusunu başlatır.")
    ayristirici.add_argument("--host", default="127.0.0.1",
                             help="Dinlenecek adres (varsayılan: 127.0.0.1)")
    ayristirici.add_argument("--port", type=int, default=8000,
                             help="Dinlenecek port (varsayılan: 8000)")
    ayristirici.add_argument("--gelistirme", action="store_true",
                             help="Kod değişince sunucuyu yeniden başlatır")
    args = ayristirici.parse_args()

    import uvicorn

    from app import config
    print(f"{config.APP_NAME} — http://{args.host}:{args.port}")
    print(f"Veritabanı: {config.database_url_safe()}")

    uvicorn.run(
        "app.web.main:app",
        host=args.host,
        port=args.port,
        reload=args.gelistirme,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
