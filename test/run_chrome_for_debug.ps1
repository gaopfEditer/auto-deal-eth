# 启动带远程调试的 Chrome，用于 Playwright CDP 连接
# Chrome 136+ 必须使用非默认 user-data-dir，否则 9222 端口不会打开
# 用法: 先关闭所有 Chrome，再运行此脚本

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$debugDir = "$env:LOCALAPPDATA\ChromeDebug"
$srcDir = "$env:LOCALAPPDATA\Google\Chrome\User Data"

if (!(Test-Path $chrome)) {
    Write-Host "[ERROR] 未找到 Chrome: $chrome" -ForegroundColor Red
    exit 1
}

# 首次或目录为空时复制
if (!(Test-Path $debugDir) -or !(Test-Path "$debugDir\Default")) {
    Write-Host "首次运行，复制配置到 $debugDir ..." -ForegroundColor Yellow
    Copy-Item $srcDir $debugDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "启动 Chrome (--remote-debugging-port=9222) ..." -ForegroundColor Green
& $chrome --remote-debugging-port=9222 --user-data-dir=$debugDir --profile-directory="Profile 1"
