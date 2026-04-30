# Windows 运行脚本
# 自动启动 Chrome 浏览器（远程调试模式）并运行项目

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  自动交易策略分析系统 - 启动脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Python 是否安装
Write-Host "[1/5] 检查 Python 环境..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ Python 已安装: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Python 未安装，请先安装 Python 3.8+" -ForegroundColor Red
    exit 1
}

# 检查虚拟环境
Write-Host "[2/5] 检查虚拟环境..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "  ✓ 虚拟环境已存在" -ForegroundColor Green
    Write-Host "  激活虚拟环境..." -ForegroundColor Gray
    & "venv\Scripts\Activate.ps1"
} else {
    Write-Host "  ⚠ 虚拟环境不存在，正在创建..." -ForegroundColor Yellow
    python -m venv venv
    & "venv\Scripts\Activate.ps1"
    Write-Host "  ✓ 虚拟环境创建完成" -ForegroundColor Green
}

# 检查并安装依赖
Write-Host "[3/5] 检查依赖包..." -ForegroundColor Yellow
$packages = @("selenium", "google-generativeai", "python-dotenv", "requests", "schedule", "pillow", "webdriver-manager")
$missingPackages = @()

foreach ($package in $packages) {
    $installed = pip show $package 2>&1
    if ($LASTEXITCODE -ne 0) {
        $missingPackages += $package
    }
}

if ($missingPackages.Count -gt 0) {
    Write-Host "  正在安装依赖包..." -ForegroundColor Gray
    pip install -r requirements.txt
    pip install webdriver-manager
    Write-Host "  ✓ 依赖包安装完成" -ForegroundColor Green
} else {
    Write-Host "  ✓ 所有依赖包已安装" -ForegroundColor Green
}

# 查找 Chrome 浏览器路径
Write-Host "[4/5] 查找 Chrome 浏览器..." -ForegroundColor Yellow
$chromePaths = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "${env:LOCALAPPDATA}\Google\Chrome\Application\chrome.exe"
)

$chromePath = $null
foreach ($path in $chromePaths) {
    if (Test-Path $path) {
        $chromePath = $path
        break
    }
}

if (-not $chromePath) {
    Write-Host "  ✗ 未找到 Chrome 浏览器，请先安装 Chrome" -ForegroundColor Red
    exit 1
}

Write-Host "  ✓ 找到 Chrome: $chromePath" -ForegroundColor Green

# 检查 Chrome 是否已在运行
Write-Host "[5/5] 检查 Chrome 进程..." -ForegroundColor Yellow
$chromeProcesses = Get-Process -Name "chrome" -ErrorAction SilentlyContinue

if ($chromeProcesses) {
    Write-Host "  ⚠ 检测到 Chrome 正在运行" -ForegroundColor Yellow
    Write-Host "  提示: 如果使用远程调试模式，请先关闭所有 Chrome 窗口" -ForegroundColor Gray
    $response = Read-Host "  是否关闭所有 Chrome 进程并重新启动? (Y/N)"
    if ($response -eq "Y" -or $response -eq "y") {
        Write-Host "  正在关闭 Chrome..." -ForegroundColor Gray
        Stop-Process -Name "chrome" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Write-Host "  ✓ Chrome 已关闭" -ForegroundColor Green
    }
}

# 启动 Chrome（远程调试模式）
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  启动 Chrome 浏览器（远程调试模式）" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$chromeDebugPort = 9222
Write-Host "  启动参数: --remote-debugging-port=$chromeDebugPort" -ForegroundColor Gray
Write-Host "  提示: Chrome 将在后台启动，您可以在浏览器中登录需要的账号" -ForegroundColor Gray
Write-Host ""

# 启动 Chrome
Start-Process -FilePath $chromePath -ArgumentList "--remote-debugging-port=$chromeDebugPort" -WindowStyle Normal

# 等待 Chrome 启动
Write-Host "  等待 Chrome 启动..." -ForegroundColor Gray
Start-Sleep -Seconds 3

# 检查远程调试端口是否可用
$portCheck = Test-NetConnection -ComputerName localhost -Port $chromeDebugPort -InformationLevel Quiet -WarningAction SilentlyContinue
if ($portCheck) {
    Write-Host "  ✓ Chrome 远程调试端口已启用" -ForegroundColor Green
} else {
    Write-Host "  ⚠ 无法确认远程调试端口，但继续运行..." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  运行 Python 程序" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查命令行参数
$runOnce = $false
if ($args.Count -gt 0 -and $args[0] -eq "--once") {
    $runOnce = $true
    Write-Host "  模式: 立即执行一次（测试模式）" -ForegroundColor Yellow
} else {
    Write-Host "  模式: 定时任务模式" -ForegroundColor Yellow
    Write-Host "  提示: 按 Ctrl+C 可退出程序" -ForegroundColor Gray
}

Write-Host ""

# 运行 Python 程序
if ($runOnce) {
    python main.py --once
} else {
    python main.py
}

Write-Host ""
Write-Host "程序已退出" -ForegroundColor Cyan

