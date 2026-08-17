@echo off
REM ============================================================
REM  Makine Ariza Takip Sistemi - tek dosya .exe uretimi
REM  Kullanim: build.bat  (proje klasorunde calistirin)
REM ============================================================
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo.
echo [1/3] Bagimliliklar kontrol ediliyor...
"%PY%" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
if errorlevel 1 goto :error

echo [2/3] Onceki derleme ciktilari temizleniyor...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [3/3] PyInstaller calisiyor (birkac dakika surebilir)...
"%PY%" -m PyInstaller MakineArizaTakip.spec --noconfirm --clean
if errorlevel 1 goto :error

echo.
echo ============================================================
echo  TAMAMLANDI
echo  Calistirilabilir dosya: dist\MakineArizaTakip.exe
echo.
echo  Tasinabilir kullanim icin exe'nin yanina bos bir
echo  "portable.txt" dosyasi koyun; veriler exe klasorundeki
echo  "data" klasorunde tutulur.
echo ============================================================
goto :end

:error
echo.
echo HATA: Derleme basarisiz oldu. Yukaridaki mesajlari kontrol edin.
exit /b 1

:end
endlocal
