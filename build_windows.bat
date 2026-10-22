@echo off
rem Build the "dist\ScanText" folder on an Internet-connected Windows PC,
rem then copy that folder to the offline PC (USB stick etc.).
rem Requirements: Python 3.10+ and Tesseract (https://github.com/UB-Mannheim/tesseract/wiki)
rem installed to the default location.
setlocal

set TESSERACT_DIR=C:\Program Files\Tesseract-OCR
if not exist "%TESSERACT_DIR%\tesseract.exe" (
  echo Tesseract not found: %TESSERACT_DIR%
  exit /b 1
)

python -m pip install -r requirements.txt pyinstaller || exit /b 1

for %%L in (jpn jpn_vert) do (
  if not exist "%TESSERACT_DIR%\tessdata\%%L.traineddata" (
    echo Downloading %%L.traineddata
    curl -L -o "%TEMP%\%%L.traineddata" https://github.com/tesseract-ocr/tessdata_fast/raw/main/%%L.traineddata || exit /b 1
    copy /y "%TEMP%\%%L.traineddata" "%TESSERACT_DIR%\tessdata\" || exit /b 1
  )
)

python -m PyInstaller --noconfirm --clean --windowed --name ScanText --collect-all tkinterdnd2 run_scantext.py || exit /b 1
xcopy /e /i /q /y "%TESSERACT_DIR%" dist\ScanText\tesseract > nul || exit /b 1
copy /y README.md dist\ScanText\ > nul

echo.
echo Done: copy the dist\ScanText folder to the offline PC.
