@echo off
chcp 65001 >nul
REM 热门资讯快速获取脚本

set SCRIPT_DIR=%~dp0
set OUTPUT_DIR=%SCRIPT_DIR%output

REM 创建输出目录
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

REM 生成带时间戳的文件名
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c-%%a-%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a-%%b)
set TIMESTAMP=%mydate%_%mytime%
set OUTPUT_FILE=%OUTPUT_DIR%\news_%TIMESTAMP%.txt

REM 解析参数
set CATEGORY=all
set SHOW_OUTPUT=1

:parse_args
if "%~1"=="" goto run
if "%~1"=="-c" (
    set CATEGORY=%~2
    shift
    shift
    goto parse_args
)
if "%~1"=="--category" (
    set CATEGORY=%~2
    shift
    shift
    goto parse_args
)
if "%~1"=="-o" (
    set OUTPUT_FILE=%~2
    set SHOW_OUTPUT=0
    shift
    shift
    goto parse_args
)
if "%~1"=="--output" (
    set OUTPUT_FILE=%~2
    set SHOW_OUTPUT=0
    shift
    shift
    goto parse_args
)
shift
goto parse_args

:run
REM 运行新闻服务
echo 📰 正在获取热门资讯...
python "%SCRIPT_DIR%news_service.py" --category %CATEGORY% --output "%OUTPUT_FILE%"

REM 显示输出
if %SHOW_OUTPUT%==1 (
    echo.
    echo 📄 新闻内容：
    echo ============================================================
    type "%OUTPUT_FILE%"
)

echo.
echo ✅ 新闻已保存到: %OUTPUT_FILE%
