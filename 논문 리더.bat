@echo off
cd /d "%~dp0"
title 논문 리더

rem 이 프로그램이 설치된 Python 을 찾는다.
rem 컴퓨터에 Python 이 여러 개 깔려 있을 수 있고(3.12 / 3.13 / 3.14 ...),
rem 그중 우리 패키지가 설치된 것만 쓸 수 있다. flask 가 import 되는지로 가려낸다.
set "PY="

py -3.12 -c "import flask" >nul 2>nul
if not errorlevel 1 set "PY=py -3.12"

if not defined PY (
    python -c "import flask" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    py -3 -c "import flask" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
    echo.
    echo   준비가 안 되어 있습니다.
    echo   아래 명령을 한 번만 실행한 뒤 다시 눌러 주세요:
    echo.
    echo       py -3.12 -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo   ==================================
echo             논  문  리  더
echo   ==================================
echo.
echo   잠시 뒤 브라우저가 열립니다.
echo   논문은 화면 안에서 PDF 를 끌어다 놓으면 들어갑니다.
echo.
echo   * 이 창을 닫으면 프로그램이 꺼집니다.
echo.

%PY% -m viewer

echo.
echo   프로그램이 종료되었습니다.
pause
