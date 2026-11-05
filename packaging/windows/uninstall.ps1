<#
  Gỡ VietDub Local cho user hiện tại (FR-040). Có chọn giữ mô hình / dữ liệu. Không đụng Python/driver dùng chung,
  không đụng Hermes hay chương trình khác.
    powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1 [-HomeDir D:\VietDubLocal] [-KeepModels] [-KeepData]
#>
param(
  [string]$HomeDir = '',
  [switch]$KeepModels,
  [switch]$KeepData
)
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'install-common.ps1')
if (-not $HomeDir) { $HomeDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
function Say($m) { Write-Host "[VietDub] $m" }

# 0. Chỉ xoá khi CHẮC là thư mục cài của VietDub: có dấu cài đặt + con trỏ phiên bản trỏ tới bản có manifest của mình
$HomeDir = [IO.Path]::GetFullPath($HomeDir).TrimEnd('\')
$AppRoot = Join-Path $HomeDir 'app'
$marker = Join-Path $AppRoot 'install-marker.json'
$cur = Join-Path $AppRoot 'current.txt'
$ok = $false
try {
  $mk = [IO.File]::ReadAllText($marker) | ConvertFrom-Json
  $ver = ([IO.File]::ReadAllText($cur)).Trim()
  $versionDir = ChildPath $AppRoot $ver
  $man = [IO.File]::ReadAllText((Join-Path $versionDir 'release-manifest.json')) | ConvertFrom-Json
  $ok = ($mk.product -eq 'VietDub Local') -and ($man.name -eq 'VietDub Local')
} catch { $ok = $false }
if (-not $ok) { Say "Không thấy bản cài VietDub Local hợp lệ ở $HomeDir — không xoá gì."; exit 1 }
$HomePat = [Management.Automation.WildcardPattern]::Escape($HomeDir)

# 1. dừng broker/tray/worker do app tạo (theo đường dẫn exe của CHÍNH bản cài, không kill tiến trình khác)
$state = Join-Path $HomeDir 'runtime\broker.json'
if (Test-Path -LiteralPath $state) {
  try { $st = [IO.File]::ReadAllText($state) | ConvertFrom-Json
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($st.port)/internal/shutdown" -Headers @{ 'X-VietDub-Pairing' = $st.pairing_secret } -TimeoutSec 5 | Out-Null } catch { }
  Start-Sleep -Seconds 3
}
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ($_.ExecutablePath -like "$HomePat\app\*" -or
    ($_.ExecutablePath -like "$HomePat\runtime\*" -and $_.CommandLine -like '*vietdub*') -or
    ($_.ExecutablePath -like "$HomePat\runtime\llama\*")) } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

# 2. registry (chỉ khi trỏ về bản cài này) + shortcut + startup
$nativeJson = Join-Path $HomeDir 'runtime\native\com.vietdub.local.json'
foreach ($k in @('HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.vietdub.local', 'HKCU:\Software\Chromium\NativeMessagingHosts\com.vietdub.local', 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.vietdub.local')) {
  if (Test-Path $k) {
    $v = (Get-ItemProperty -Path $k).'(default)'
    if ($v -and ([IO.Path]::GetFullPath($v) -eq $nativeJson)) { Remove-Item -Force $k; Say "Đã xóa $k" }
    else { Say "Giữ $k (đang trỏ tới bản cài khác: $v)" }
  }
}
$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$rv = (Get-ItemProperty -Path $run -Name 'VietDubLocal' -ErrorAction SilentlyContinue).VietDubLocal
if ($rv -and $rv -like "*$HomePat*") { Remove-ItemProperty -Path $run -Name 'VietDubLocal' -ErrorAction SilentlyContinue }
$sh = New-Object -ComObject WScript.Shell
foreach ($name in @('VietDub Local.lnk','VietDub - Huong dan.lnk')) {
  $lnk = Join-Path ([Environment]::GetFolderPath('Programs')) $name
  if (Test-Path -LiteralPath $lnk) {
    $target = $sh.CreateShortcut($lnk).TargetPath
    if ($target.StartsWith($HomeDir+'\',[StringComparison]::OrdinalIgnoreCase)) { Remove-Item -Force -LiteralPath $lnk }
  }
}

# 3. tệp — chỉ các thư mục con do VietDub tạo, không xoá cả HomeDir mù quáng
function RmHome([string[]]$names) {
  foreach ($n in $names) { $p = ChildPath $HomeDir $n; if (Test-Path -LiteralPath $p) { Remove-Item -Recurse -Force -LiteralPath $p -ErrorAction SilentlyContinue } }
}
RmHome @('app', 'runtime\native', 'runtime\broker.json', 'extension', 'HUONG-DAN.html')
if (-not $KeepData) {
  RmHome @('db', 'cache', 'logs', 'exports', 'diagnostics', 'backups', 'tmp', 'local-config.json')
  Say 'Đã xóa dữ liệu, bộ nhớ đệm, bản sửa, nhật ký.'
} else { Say 'Giữ dữ liệu (db/cache/bản sửa).' }
if (-not $KeepModels) {
  RmHome @('models', 'runtime')
  Say 'Đã xóa mô hình và runtime.'
} else { Say 'Giữ mô hình và runtime.' }
if (-not $KeepData -and -not $KeepModels) { RmHome @('.vietdub-install.json') }
if (-not (Get-ChildItem -Force -LiteralPath $HomeDir -ErrorAction SilentlyContinue)) { Remove-Item -Force -LiteralPath $HomeDir -ErrorAction SilentlyContinue }
Say 'Đã gỡ VietDub Local. Nhớ gỡ tiện ích trong chrome://extensions.'
