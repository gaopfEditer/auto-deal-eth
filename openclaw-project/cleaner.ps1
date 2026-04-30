# 全局清理脚本 (Windows)
# 建议任务计划程序每周执行
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 1. 删除 logs/ 下超过 7 天的滚动文件
Get-ChildItem -Path "logs" -Recurse -Filter "*.log.*" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force

# 2. temp 临时目录
if (Test-Path "temp") { Remove-Item -Path "temp\*" -Recurse -Force }

# 3. 临时 .ts 分片
Get-ChildItem -Path "." -Recurse -Filter "*.ts" | Where-Object { $_.FullName -like "*temp*" -and $_.LastWriteTime -lt (Get-Date).AddDays(-1) } | Remove-Item -Force

Write-Host "[OK] cleaner.ps1 执行完成" -ForegroundColor Green
