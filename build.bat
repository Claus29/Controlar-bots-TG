@echo off
REM Compila BotControl y su instalador en Windows.
REM Requisitos: Python 3.10+ (con "Add to PATH") e Inno Setup 6 (https://jrsoftware.org/isdl.php)
setlocal
cd /d "%~dp0"

if not exist .build-venv (
    py -3 -m venv .build-venv 2>nul || python -m venv .build-venv || goto :error
)
call .build-venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt -r requirements-dev.txt || goto :error

echo.
echo === Tests ===
python -m pytest -q || goto :error

echo.
echo === Empaquetando con PyInstaller ===
for /f %%v in ('python installer\make_version_info.py') do set VERSION=%%v
pyinstaller --noconfirm --clean botcontrol.spec || goto :error

echo.
echo === Creando instalador ===
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo No se encontro Inno Setup 6. La version portable esta en dist\BotControl\BotControl.exe
    goto :end
)
%ISCC% /DMyAppVersion=%VERSION% installer\BotControl.iss || goto :error
echo.
echo Instalador listo: dist\installer\BotControl-Setup-%VERSION%.exe
goto :end

:error
echo.
echo *** Error durante la compilacion ***
exit /b 1

:end
endlocal
