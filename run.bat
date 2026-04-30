@echo off
chcp 65001 >nul
echo ========================================
echo   自动交易策略分析系统 - 启动脚本
echo ========================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 激活虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] 虚拟环境已激活
) else (
    echo [INFO] 创建虚拟环境...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo [OK] 虚拟环境已创建
)

REM 安装依赖
echo [INFO] 检查依赖包...
pip install -r requirements.txt -q

REM 启动 Chrome（远程调试模式）
echo.
echo ========================================
echo   启动 Chrome 浏览器
echo ========================================
echo.

set CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME_PATH%" (
    set CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
)
if not exist "%CHROME_PATH%" (
    set CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
)

if exist "%CHROME_PATH%" (
    echo [INFO] 启动 Chrome（远程调试模式）...
    start "" "%CHROME_PATH%" --remote-debugging-port=9222
    timeout /t 3 /nobreak >nul
    echo [OK] Chrome 已启动
) else (
    echo [WARNING] 未找到 Chrome，将使用直接打开模式
    set USE_REMOTE_DEBUGGING=False
)

echo.
echo ========================================
echo   运行 Python 程序
echo ========================================
echo.

REM 检查命令行参数
set ARGS=%*
if "%ARGS%"=="" (
    echo [INFO] 模式: 定时任务模式（浏览器网页版模式）
    echo [INFO] 提示: 按 Ctrl+C 可退出程序
    echo [INFO] 使用 --api 参数可切换到 API 模式
    echo.
    python main.py
) else (
    echo [INFO] 运行参数: %ARGS%
    python main.py %ARGS%
)

echo.
echo 程序已退出
pause

