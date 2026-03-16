@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   Message Hub 守护进程管理器
echo ========================================
echo.

if "%1"=="" (
    echo 使用方法:
    echo   start-daemon.bat start    启动守护进程
    echo   start-daemon.bat stop     停止守护进程
    echo   start-daemon.bat restart  重启守护进程
    echo   start-daemon.bat status   查看状态
    echo.
    echo 功能:
    echo   • 保持 WebSocket 连接在后台运行
    echo   • 自动重启崩溃的进程
    echo   • 最大重试次数: 10 次
    echo   • 重试延迟: 5 秒
    echo.
    goto :end
)

cd /d "%~dp0"

if "%1"=="start" (
    echo [INFO] 启动 message-hub 守护进程...
    echo [INFO] 进程将在后台运行，日志保存在 auto-restart.log
    echo.
    start "Message Hub Daemon" /B node auto-restart.js start
    echo ✅ 守护进程已启动
    echo 📝 查看日志: type auto-restart.log
    goto :end
)

if "%1"=="stop" (
    echo [INFO] 停止 message-hub 守护进程...
    echo.
    node auto-restart.js stop
    goto :end
)

if "%1"=="restart" (
    echo [INFO] 重启 message-hub 守护进程...
    echo.
    node auto-restart.js stop
    timeout /t 2 /nobreak >nul
    start "Message Hub Daemon" /B node auto-restart.js start
    echo ✅ 守护进程已重启
    goto :end
)

if "%1"=="status" (
    echo [INFO] 检查 message-hub 状态...
    echo.
    tasklist /FI "WINDOWTITLE eq Message Hub Daemon" /FO TABLE
    echo.
    if exist "auto-restart.log" (
        echo 📝 最后 10 行日志:
        echo ----------------------------------------
        tail -n 10 auto-restart.log 2>nul || (
            for /f "skip=-10" %%i in (auto-restart.log) do echo %%i
        )
        echo ----------------------------------------
    ) else (
        echo ℹ️ 未找到日志文件
    )
    goto :end
)

echo ❌ 未知命令: %1
echo 使用 start-daemon.bat 查看帮助

:end
echo.
pause