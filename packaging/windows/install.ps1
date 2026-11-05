# Windows PowerShell 5.1. No administrator or globally installed Python required.
[CmdletBinding()]
param(
 [string]$HomeDir = $(if (Test-Path 'D:\') { 'D:\VietDubLocal' } else { Join-Path $env:LOCALAPPDATA 'VietDubLocal' }),
 [switch]$AcceptDownloads, [switch]$IncludeAsr, [switch]$StartWithWindows,
 [switch]$NoLaunch, [switch]$NoShortcut, [switch]$NoRegistration, [switch]$CheckOnly,
 [switch]$UseExistingRuntime, [string]$TtsPython='', [string]$AsrPython='',
 [string]$LlamaFrom='', [string]$LlamaZipDir=''
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$Pkg=$PSScriptRoot
. (Join-Path $Pkg 'install-common.ps1')
function Say($m) { Write-Host "[VietDub] $m" }
function Run([string]$Exe,[string[]]$Arguments,[string]$Step) { InvokeNativeChecked $Exe $Arguments $InstallLog $Step }
function SetPointer([string]$Name) {
 WriteText "$CurFile.tmp" $Name
 if (Test-Path -LiteralPath $CurFile) { [IO.File]::Replace("$CurFile.tmp",$CurFile,[NullString]::Value) }
 else { [IO.File]::Move("$CurFile.tmp",$CurFile) }
}
function StopOwned {
 if (Test-Path -LiteralPath $StateFile) {
  try {
   $st=Get-Content -Raw -Encoding UTF8 -LiteralPath $StateFile | ConvertFrom-Json
   $p=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$st.pid)"
   if ($p.ExecutablePath -and $p.ExecutablePath.StartsWith($HomeDir+'\',[StringComparison]::OrdinalIgnoreCase)) {
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$([int]$st.port)/internal/shutdown" -Headers @{'X-VietDub-Pairing'=$st.pairing_secret} -TimeoutSec 3 | Out-Null
    Start-Sleep -Seconds 2
   }
  } catch { }
 }
 Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -and $_.ExecutablePath.StartsWith($HomeDir+'\',[StringComparison]::OrdinalIgnoreCase) -and
  ($_.CommandLine -like '*vietdub*' -or $_.ExecutablePath -like '*\llama-server.exe')
 } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
 if (Test-Path -LiteralPath $StateFile) { Remove-Item -LiteralPath $StateFile -Force }
}
try {
 Say '1/7 Kiểm tra gói cài đặt và thư mục đích...'
 $manifest=ReadVerifiedPackage $Pkg
 $HomeDir=ResolveInstallHome $HomeDir $Pkg
 if (-not [Environment]::Is64BitOperatingSystem) { throw 'Cần Windows x64.' }
 if ($CheckOnly) { Say "CHECK_OK $($manifest.version) -> $HomeDir"; exit 0 }
 if (-not $AcceptDownloads) { throw 'Chưa đồng ý tải. Hãy chạy Setup.cmd hoặc thêm -AcceptDownloads.' }
 $drive=New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($HomeDir))
 if ($drive.AvailableFreeSpace -lt 20GB) { throw 'Cần ít nhất 20 GB trống cho môi trường, model và bộ nhớ đệm.' }
 $AppRoot=ChildPath $HomeDir 'app'
 foreach ($rel in @('app','runtime','models','cache\uv','tmp','logs')) { New-Item -ItemType Directory -Force -Path (ChildPath $HomeDir $rel) | Out-Null }
 WriteText (Join-Path $HomeDir '.vietdub-install.json') '{"product":"VietDub Local"}'
 $InstallLog=ChildPath $HomeDir 'logs\install.log'
 Add-Content -Encoding UTF8 -LiteralPath $InstallLog "$(Get-Date -Format s) install $($manifest.version)"
 $env:UV_CACHE_DIR=ChildPath $HomeDir 'cache\uv'; $env:UV_PYTHON_INSTALL_DIR=ChildPath $HomeDir 'runtime\python'
 $env:UV_NO_MODIFY_PATH='1'; $env:UV_PYTHON_INSTALL_BIN='0'; $env:UV_PYTHON_INSTALL_REGISTRY='0'
 $env:TEMP=ChildPath $HomeDir 'tmp'; $env:TMP=$env:TEMP
 $CurFile=ChildPath $HomeDir 'app\current.txt'; $StateFile=ChildPath $HomeDir 'runtime\broker.json'
 $Prev=if (Test-Path -LiteralPath $CurFile) { ([IO.File]::ReadAllText($CurFile)).Trim() } else { '' }
 if ($Prev -and $Prev -notmatch '^\d+\.\d+\.\d+(-r[0-9a-f]+)?$') { throw 'Con trỏ bản cũ không hợp lệ.' }
 $DirName="$($manifest.version)-r$([Guid]::NewGuid().ToString('N').Substring(0,10))"
 $AppDir=ChildPath $AppRoot $DirName
 Copy-Item -LiteralPath (Join-Path $Pkg 'app') -Destination $AppDir -Recurse
 Copy-Item -LiteralPath (Join-Path $Pkg 'release-manifest.json') -Destination (Join-Path $AppDir 'release-manifest.json')
 WriteText (Join-Path $AppDir 'vietdub-home.txt') $HomeDir
 $uv=Join-Path $AppDir 'bin\uv.exe'
 Say '2/7 Cài Python riêng và bộ xử lý. Chi tiết tải: logs\install.log.'
 Run $uv @('python','install',$manifest.python_version) 'Tải/kiểm Python riêng'
 $py=Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Directory -Filter "cpython-$($manifest.python_version)-*" | ForEach-Object { Join-Path $_.FullName 'python.exe' } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
 if (-not $py) { throw 'Không tìm thấy Python sau khi cài.' }
 Run $uv @('venv',"$AppDir\venv",'--python',$py) 'Tạo môi trường bộ xử lý'
 Run $uv @('pip','sync','--python',"$AppDir\venv\Scripts\python.exe",'--require-hashes',"$AppDir\requirements\broker.lock.txt") 'Cài thư viện bộ xử lý'
 Run $uv @('pip','check','--python',"$AppDir\venv\Scripts\python.exe") 'Kiểm thư viện bộ xử lý'
 Say '3/7 Chuẩn bị bộ chạy dịch llama.cpp...'
 $llamaDir=ChildPath $HomeDir ("runtime\llama\"+$manifest.llama.directory)
 $server=Join-Path $llamaDir 'llama-server.exe'
 $serverOk=(Test-Path -LiteralPath $server) -and (Sha $server) -eq $manifest.llama.server_sha256
 if (-not $serverOk) {
  New-Item -ItemType Directory -Force -Path $llamaDir | Out-Null
  if ($LlamaFrom) {
   if ((Sha (Join-Path $LlamaFrom 'llama-server.exe')) -ne $manifest.llama.server_sha256) { throw 'Runtime cung cấp không khớp bản ghim.' }
   Get-ChildItem -LiteralPath $LlamaFrom | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $llamaDir -Recurse -Force }
  } else {
   $downloads=ChildPath $HomeDir 'runtime\downloads'; New-Item -ItemType Directory -Force -Path $downloads | Out-Null
   foreach ($z in $manifest.llama.zips) {
    if ($z.name -notmatch '^[a-zA-Z0-9._-]+\.zip$' -or $z.url -notlike 'https://github.com/ggml-org/llama.cpp/releases/download/*') { throw 'Nguồn runtime không hợp lệ.' }
    $dst=ChildPath $downloads $z.name
    if ($LlamaZipDir -and (Test-Path -LiteralPath (Join-Path $LlamaZipDir $z.name))) { Copy-Item -LiteralPath (Join-Path $LlamaZipDir $z.name) -Destination $dst -Force }
    if ((Test-Path -LiteralPath $dst) -and (Sha $dst) -ne $z.sha256) { Remove-Item -LiteralPath $dst -Force }
    if (-not (Test-Path -LiteralPath $dst)) {
     Run 'curl.exe' @('-fSL','--retry','3','-C','-','-o',"$dst.part",$z.url) "Tải $($z.name) (có thể tiếp tục khi mất mạng)"
     if ((Sha "$dst.part") -ne $z.sha256) { Remove-Item -LiteralPath "$dst.part" -Force; throw 'Checksum runtime sai. Chạy lại để tải mới.' }
     Move-Item -LiteralPath "$dst.part" -Destination $dst -Force
    }
    Expand-Archive -LiteralPath $dst -DestinationPath $llamaDir -Force
   }
  }
  if ((Sha $server) -ne $manifest.llama.server_sha256) { throw 'llama-server không khớp SHA đã ghim.' }
 }
 Say '4/7 Chuẩn bị giọng đọc và nhận dạng âm thanh...'
 $cfgPath=ChildPath $HomeDir 'local-config.json'
 $oldConfig=if (Test-Path -LiteralPath $cfgPath) { [IO.File]::ReadAllText($cfgPath) } else { $null }
 $cfg=@{}; if ($oldConfig) { ($oldConfig | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $cfg[$_.Name]=$_.Value } }
 if ($UseExistingRuntime) {
  if (-not $TtsPython -or -not (Test-Path -LiteralPath $TtsPython -PathType Leaf)) { throw 'Thiếu -TtsPython hợp lệ.' }
  $cfg.tts_python=$TtsPython
  if ($AsrPython) { if (-not (Test-Path -LiteralPath $AsrPython -PathType Leaf)) { throw 'AsrPython không tồn tại.' }; $cfg.asr_python=$AsrPython }
 } else {
  $kinds=@('tts'); if ($IncludeAsr) { $kinds+='asr' }
  foreach ($kind in $kinds) {
   $lock=Join-Path $AppDir "requirements\$kind.lock.txt"; $fingerprint=Sha $lock
   # Separate environment for each lock: preserve the previous version during updates.
   $venv=ChildPath $HomeDir ("runtime\venv-$kind-"+$fingerprint.Substring(0,12))
   $python=Join-Path $venv 'Scripts\python.exe'; $complete=Join-Path $venv 'vietdub-ready.txt'
   if (-not (Test-Path -LiteralPath $python)) { Run $uv @('venv',$venv,'--python',$py) "Tạo môi trường $kind" }
   if (-not (Test-Path -LiteralPath $complete) -or ([IO.File]::ReadAllText($complete)).Trim() -ne $fingerprint) {
    Run $uv @('pip','sync','--python',$python,$lock,'--extra-index-url','https://download.pytorch.org/whl/cu128','--index-strategy','unsafe-best-match') "Tải thư viện $kind (lần đầu có thể vài GB)"
    Run $uv @('pip','check','--python',$python) "Kiểm thư viện $kind"
    $imports=if ($kind -eq 'tts') { 'import vieneu, torch, numpy' } else { 'import faster_whisper, numpy' }
    Run $python @('-B','-c',$imports) "Kiểm khởi động môi trường $kind"
    WriteText $complete $fingerprint
   }
   $cfg["${kind}_python"]=$python
  }
 }
 $cfg.llama_server=$server; $cfg.llama_build=$manifest.llama.build
 $cfg.allowed_extension_ids=[object[]]@(@($manifest.extension_ids)+@($cfg.allowed_extension_ids | Where-Object { $_ -match '^[a-p]{32}$' }) | Select-Object -Unique)
 Say '5/7 Khởi động và kiểm tra bộ xử lý...'
 $native=ChildPath $HomeDir 'runtime\native'; New-Item -ItemType Directory -Force -Path $native | Out-Null
 # ASCII launchers derive the chosen home at runtime, including Vietnamese paths.
 $launch=@'
@echo off
for %%I in ("%~dp0..\..") do set "VIETDUB_HOME=%%~fI"
set /p VDVER=<"%VIETDUB_HOME%\app\current.txt"
set "VDAPP=%VIETDUB_HOME%\app\%VDVER%"
set "PYTHONPATH=%VDAPP%\services"
set PYTHONIOENCODING=utf-8
'@
 WriteText "$native\vietdub-native-host.cmd" ($launch+"`r`n`"%VDAPP%\venv\Scripts\python.exe`" -B -m vietdub.native_host %*`r`n")
 WriteText "$native\vietdub-tray.cmd" ($launch+"`r`nstart `"`" `"%VDAPP%\venv\Scripts\pythonw.exe`" -B -m vietdub.companion.tray`r`n")
 StopOwned
 WriteText $cfgPath ($cfg | ConvertTo-Json -Depth 8)
 SetPointer $DirName; $switched=$true
 if (-not $NoLaunch) {
  Start-Process -FilePath "$native\vietdub-tray.cmd" -WindowStyle Hidden
  $ok=$false
  for ($i=0; $i -lt 45 -and -not $ok; $i++) {
   Start-Sleep -Seconds 2
   try {
    $st=Get-Content -Raw -Encoding UTF8 -LiteralPath $StateFile | ConvertFrom-Json
    $h=Invoke-RestMethod -Uri "http://127.0.0.1:$([int]$st.port)/health" -TimeoutSec 2
    $ok=$h.protocol_version -eq 1 -and $st.app_version -eq $manifest.version
   } catch { }
  }
  if (-not $ok) { throw 'Bộ xử lý mới không khởi động được. Xem logs\broker-stderr.log.' }
 }
 Say '6/7 Lưu tiện ích cố định và đăng ký kết nối trình duyệt...'
 $ext=ChildPath $HomeDir 'extension'
 if (Test-Path -LiteralPath $ext) { $extBackup=ChildPath $AppDir 'previous-extension'; Move-Item -LiteralPath $ext -Destination $extBackup }
 Copy-Item -LiteralPath (Join-Path $Pkg 'extension') -Destination $ext -Recurse
 $nm=@{name='com.vietdub.local';description='VietDub Local';path="$native\vietdub-native-host.cmd";type='stdio';allowed_origins=@($cfg.allowed_extension_ids | ForEach-Object { "chrome-extension://$_/" })}
 WriteText "$native\com.vietdub.local.json" ($nm | ConvertTo-Json -Depth 4)
 if (-not $NoRegistration) {
  foreach ($k in @('HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.vietdub.local','HKCU:\Software\Chromium\NativeMessagingHosts\com.vietdub.local','HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.vietdub.local')) {
   New-Item -Force -Path $k | Out-Null; Set-Item -LiteralPath $k -Value "$native\com.vietdub.local.json"
  }
 }
 foreach ($file in @('uninstall.ps1','install-common.ps1')) { Copy-Item -LiteralPath (Join-Path $Pkg $file) -Destination (Join-Path $AppRoot $file) -Force }
 WriteText (Join-Path $AppRoot 'install-marker.json') '{"product":"VietDub Local"}'
 if ($Prev) { WriteText (Join-Path $AppRoot 'previous.txt') $Prev }
 $guide=[IO.File]::ReadAllText((Join-Path $Pkg 'HUONG-DAN.html')).Replace('{{EXTENSION_PATH}}',[Net.WebUtility]::HtmlEncode($ext))
 WriteText (Join-Path $HomeDir 'HUONG-DAN.html') $guide
 if (-not $NoShortcut) {
  $sh=New-Object -ComObject WScript.Shell
  foreach ($entry in @(@('VietDub Local.lnk',"$native\vietdub-tray.cmd"),@('VietDub - Huong dan.lnk',(Join-Path $HomeDir 'HUONG-DAN.html')))) {
   $shortcut=$sh.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) $entry[0]))
   $shortcut.TargetPath=$entry[1]; $shortcut.WindowStyle=7; $shortcut.IconLocation="$AppDir\assets\vietdub.ico"; $shortcut.Save()
  }
 }
 if (-not $NoRegistration -and $StartWithWindows) { Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'VietDubLocal' -Value "`"$native\vietdub-tray.cmd`"" }
 $switched=$false
 Say "7/7 INSTALL_OK $($manifest.version)"; Say "Nạp tiện ích tại: $ext"
 Say 'Mở hướng dẫn, nạp tiện ích, bấm Kết nối rồi Chuẩn bị để sử dụng.'
 exit 0
} catch {
 $failure=$_.Exception.Message
 if ($switched) {
  try {
   StopOwned
   if ($oldConfig) { WriteText $cfgPath $oldConfig }
   if ($Prev) { SetPointer $Prev; if (-not $NoLaunch) { Start-Process -FilePath "$native\vietdub-tray.cmd" -WindowStyle Hidden } }
   elseif (Test-Path -LiteralPath $CurFile) { Remove-Item -LiteralPath $CurFile -Force }
   if ($extBackup -and (Test-Path -LiteralPath $extBackup)) {
    if (Test-Path -LiteralPath $ext) { $safe=ChildPath $HomeDir 'extension'; Remove-Item -LiteralPath $safe -Recurse -Force }
    Move-Item -LiteralPath $extBackup -Destination $ext
   }
   Say 'Đã trả về phiên bản trước (nếu có).'
  } catch { Say "Không khôi phục được hoàn toàn: $($_.Exception.Message)" }
 }
 Write-Host "[VietDub] INSTALL_FAILED: $failure" -ForegroundColor Red
 exit 1
}
