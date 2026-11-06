# Native Windows setup screen. Uses only the Windows .NET Framework.
param([string]$PreviewImage='', [ValidateSet('idle','download','packages','done','failed')][string]$PreviewState='idle', [string]$ExistingHome='')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
. (Join-Path $PSScriptRoot 'install-common.ps1')
$script:installProcess=$null; $script:installedHome=$null; $script:stdoutPath=$null
$script:startedAt=$null; $script:progressPath=$null; $script:liveLog=$null; $script:stderrPath=$null
$form=New-Object Windows.Forms.Form
$form.Text='Cài đặt VietDub Local'; $form.ClientSize=New-Object Drawing.Size(720,690)
$form.StartPosition='CenterScreen'; $form.FormBorderStyle='FixedDialog'; $form.MaximizeBox=$false
$form.Font=New-Object Drawing.Font('Segoe UI',10)
$form.BackColor=[Drawing.Color]::White
function LabelAt($Text,$X,$Y,$W,$H) {
 $c=New-Object Windows.Forms.Label; $c.Text=$Text; $c.Location=New-Object Drawing.Point($X,$Y); $c.Size=New-Object Drawing.Size($W,$H); $form.Controls.Add($c); return $c
}
$title=LabelAt 'VietDub Local' 28 22 660 40
$title.Font=New-Object Drawing.Font('Segoe UI',22,[Drawing.FontStyle]::Bold)
$null=LabelAt 'Nghe phụ đề video YouTube bằng giọng Việt. AI xử lý ngay trên máy.' 30 72 660 30
$null=LabelAt 'Windows 10/11 x64 · NVIDIA · khuyên dùng RAM 32 GB · ổ trống 20 GB' 30 105 660 30
$null=LabelAt 'Nơi lưu chương trình, mô hình và bộ nhớ đệm' 30 132 660 25
$folder=New-Object Windows.Forms.TextBox; $folder.Location=New-Object Drawing.Point(30,160); $folder.Size=New-Object Drawing.Size(550,28)
$folder.Text=if (Test-Path 'D:\') { 'D:\VietDubLocal' } else { Join-Path $env:LOCALAPPDATA 'VietDubLocal' }; $form.Controls.Add($folder)
if ($ExistingHome) { $folder.Text=$ExistingHome }
$browse=New-Object Windows.Forms.Button; $browse.Text='Chọn...'; $browse.Location=New-Object Drawing.Point(590,157); $browse.Size=New-Object Drawing.Size(100,34); $form.Controls.Add($browse)
$browse.Add_Click({
 $dialog=New-Object Windows.Forms.FolderBrowserDialog; $dialog.Description='Chọn thư mục trống hoặc bản cài VietDub bằng bộ cài này'
 if ($dialog.ShowDialog() -eq 'OK') { $folder.Text=$dialog.SelectedPath }; $dialog.Dispose()
})
function CheckAt($Text,$Y) {
 $c=New-Object Windows.Forms.CheckBox; $c.Text=$Text; $c.Location=New-Object Drawing.Point(30,$Y); $c.Size=New-Object Drawing.Size(660,30); $form.Controls.Add($c); return $c
}
$asr=CheckAt 'Thêm nhận dạng âm thanh tiếng Anh khi không có phụ đề (có thể cài sau)' 200
$startup=CheckAt 'Tự mở VietDub khi đăng nhập Windows' 231
if ($ExistingHome) {
 try { $old=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $ExistingHome 'local-config.json') | ConvertFrom-Json; $asr.Checked=!!$old.asr_python } catch { }
 try { $startup.Checked=!!(Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'VietDubLocal' -ErrorAction Stop).VietDubLocal } catch { }
}
$notice=LabelAt "Lần đầu cần tải vài GB thư viện từ Python/PyPI, PyTorch và GitHub.`r`nMô hình AI tải riêng trong tiện ích, có hiển thị dung lượng và giấy phép.`r`nChỉ bắt đầu tải khi bạn bấm Cài đặt." 30 270 660 62
$consent=CheckAt 'Tôi đồng ý tải các thành phần cần thiết để cài đặt.' 337
$consent.Checked=$true
$stepLabel=LabelAt 'Sẵn sàng cài đặt' 30 372 660 24
$stepLabel.Font=New-Object Drawing.Font('Segoe UI',10,[Drawing.FontStyle]::Bold)
$overall=New-Object Windows.Forms.ProgressBar; $overall.Location=New-Object Drawing.Point(30,399); $overall.Size=New-Object Drawing.Size(660,10); $overall.Maximum=7; $form.Controls.Add($overall)
$activity=LabelAt 'Chọn nơi lưu rồi bấm Cài đặt.' 30 418 660 24; $activity.AutoEllipsis=$true
$transfer=New-Object Windows.Forms.ProgressBar; $transfer.Location=New-Object Drawing.Point(30,446); $transfer.Size=New-Object Drawing.Size(660,14); $transfer.MarqueeAnimationSpeed=25; $form.Controls.Add($transfer)
$detail=LabelAt 'Tiến trình từng thành phần sẽ hiển thị tại đây.' 30 470 660 39; $detail.AutoEllipsis=$true
$status=New-Object Windows.Forms.TextBox; $status.Multiline=$true; $status.ReadOnly=$true; $status.ScrollBars='Vertical'
$status.Location=New-Object Drawing.Point(30,514); $status.Size=New-Object Drawing.Size(660,96)
$status.Text='Chọn nơi lưu rồi bấm Cài đặt. Có thể bỏ tích đồng ý nếu chưa muốn tải.'; $form.Controls.Add($status)
$elapsed=LabelAt '' 30 612 660 20; $elapsed.Font=New-Object Drawing.Font('Segoe UI',9)
$install=New-Object Windows.Forms.Button; $install.Text='Cài đặt'; $install.Enabled=$true
$install.Location=New-Object Drawing.Point(480,640); $install.Size=New-Object Drawing.Size(120,36); $form.Controls.Add($install)
$close=New-Object Windows.Forms.Button; $close.Text='Đóng'; $close.Location=New-Object Drawing.Point(610,640); $close.Size=New-Object Drawing.Size(80,36); $form.Controls.Add($close)
$guide=New-Object Windows.Forms.Button; $guide.Text='Mở hướng dẫn'; $guide.Location=New-Object Drawing.Point(30,640); $guide.Size=New-Object Drawing.Size(155,36); $guide.Enabled=$false; $form.Controls.Add($guide)
$guide.Add_Click({ if ($script:installedHome) { Start-Process -FilePath (Join-Path $script:installedHome 'HUONG-DAN.html') } })
$close.Add_Click({$form.Close()})
$consent.Add_CheckedChanged({$install.Enabled=$consent.Checked -and -not $script:installProcess})
function ShowInstallProgress($snapshot) {
 $view=InstallProgressView $snapshot
 $stepLabel.Text=$view.title; $overall.Value=$view.completed; $activity.Text=$view.activity; $detail.Text=$view.detail
 if ($null -ne $view.percent) { $transfer.Style='Continuous'; $transfer.Value=$view.percent }
 elseif ($snapshot.state -eq 'failed') { $transfer.Style='Continuous'; $transfer.Value=0 }
 else { $transfer.Style='Marquee' }
}
function RefreshInstallDisplay {
 if ($script:progressPath -and (Test-Path -LiteralPath $script:progressPath)) {
  try { ShowInstallProgress (Get-Content -Raw -Encoding UTF8 -LiteralPath $script:progressPath | ConvertFrom-Json) } catch { }
 }
 try {
  $text=ReadInstallLogTail $script:liveLog
  if (-not $text) { $text=ReadInstallLogTail $script:stdoutPath }
  if ($text -and $text -ne $status.Text) { $status.Text=$text; $status.SelectionStart=$status.Text.Length; $status.ScrollToCaret() }
 } catch { }
 if ($script:startedAt) {
  $span=(Get-Date)-$script:startedAt; $elapsed.Text=('Đã chạy {0:00}:{1:00}:{2:00}' -f [int][Math]::Floor($span.TotalHours),$span.Minutes,$span.Seconds)
  if ($script:liveLog -and (Test-Path -LiteralPath $script:liveLog)) {
   $seconds=[int]((Get-Date)-(Get-Item -LiteralPath $script:liveLog).LastWriteTime).TotalSeconds
   $elapsed.Text+=" • Log cập nhật cách đây $seconds giây"
  }
 }
}
$timer=New-Object Windows.Forms.Timer; $timer.Interval=700
$timer.Add_Tick({
 if (-not $script:installProcess) { return }
 RefreshInstallDisplay
 $script:installProcess.Refresh()
 if ($script:installProcess.HasExited) {
  $timer.Stop(); $script:installProcess.WaitForExit(); $code=$script:installProcess.ExitCode
  RefreshInstallDisplay
  $script:installProcess.Dispose(); $script:installProcess=$null
  foreach ($c in @($folder,$browse,$asr,$startup,$consent,$close)) { $c.Enabled=$true }
  $install.Enabled=$consent.Checked; $install.Text='Thử lại'
  if ($code -eq 0) {
   ShowInstallProgress @{step=7;state='done';activity='Cài đặt hoàn tất'}
   $status.AppendText("`r`nĐã cài xong. Bấm Mở hướng dẫn để thêm tiện ích vào Chrome.")
   $guide.Enabled=$true; $install.Enabled=$false
  } else {
   $reason=if ($null -eq $code) { 'Không nhận được mã kết thúc. Kiểm logs trước khi cài lại.' } else { "Bộ cài kết thúc với mã $code. Xem log bên dưới hoặc logs\install.log." }
   $stepLabel.Text='Chưa xác nhận cài thành công'; $detail.Text=$reason; $transfer.Style='Continuous'; $transfer.Value=0
   $errorText=ReadInstallLogTail $script:stderrPath
   if ($errorText) { $status.AppendText("`r`n"+$errorText) }
   $status.AppendText("`r`n"+$reason)
  }
 }
})
function PSLiteral([string]$Value) { return "'"+$Value.Replace("'","''")+"'" }
$install.Add_Click({
 try {
  $status.Text='Đang kiểm tra gói và nơi lưu...'; $form.Refresh()
  $null=ReadVerifiedPackage $PSScriptRoot
  $target=ResolveInstallHome $folder.Text $PSScriptRoot
  $drive=New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($target))
  if ($drive.AvailableFreeSpace -lt 20GB) { throw 'Ổ đĩa cần ít nhất 20 GB trống.' }
  if (-not (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)) { throw 'Chưa tìm thấy driver NVIDIA (nvidia-smi). Cài driver NVIDIA phù hợp rồi thử lại.' }
  # Resume marker is written before any partial installation. It grants no download consent itself.
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  WriteText (Join-Path $target '.vietdub-install.json') '{"product":"VietDub Local"}'
  $logs=ChildPath $target 'logs'; New-Item -ItemType Directory -Force -Path $logs | Out-Null
  $script:stdoutPath=Join-Path $logs 'setup-output.log'; $script:stderrPath=Join-Path $logs 'setup-error.log'
  $script:progressPath=ChildPath $target 'logs\install-progress.json'; $script:liveLog=ChildPath $target 'logs\install-live.log'
  if (Test-Path -LiteralPath $script:progressPath) { Remove-Item -LiteralPath $script:progressPath -Force }
  WriteText $script:liveLog ''
  $cmd='[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference=''SilentlyContinue''; & '+(PSLiteral (Join-Path $PSScriptRoot 'install.ps1'))+' -HomeDir '+(PSLiteral $target)+' -AcceptDownloads'
  if ($asr.Checked) { $cmd+=' -IncludeAsr' }; if ($startup.Checked) { $cmd+=' -StartWithWindows' }
  $cmd+='; exit $LASTEXITCODE'
  $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
  $script:installProcess=StartInstallerProcess $encoded $script:stdoutPath $script:stderrPath
  $script:startedAt=Get-Date
  $script:installedHome=$target
  foreach ($c in @($folder,$browse,$asr,$startup,$consent,$install,$close,$guide)) { $c.Enabled=$false }
  $status.Text='Đang cài. Có thể mất nhiều phút ở lần đầu; không tắt máy.'
  ShowInstallProgress @{step=1;state='running';activity='Kiểm tra gói và thư mục cài'}
  $timer.Start()
 } catch { $status.Text=$_.Exception.Message; $install.Enabled=$consent.Checked }
})
$form.Add_FormClosing({ if ($script:installProcess) { $_.Cancel=$true; $status.AppendText("`r`nĐang cài, vui lòng chờ hoàn tất để tránh làm gián đoạn.") } })
$form.Add_FormClosed({$timer.Stop(); $timer.Dispose()})
if ($PreviewImage) {
 # Render actual WinForms controls for local UI verification; no installation or download.
 $form.Show(); $form.Refresh(); [Windows.Forms.Application]::DoEvents()
 if (-not $install.Enabled -or -not $consent.Checked) { throw 'Download consent must be checked by default.' }
 $consent.Checked=$false
 if ($install.Enabled) { throw 'Revoking consent must disable Install.' }
 $consent.Checked=$true
 if (-not $install.Enabled) { throw 'Consent does not enable Install.' }
 if ($PreviewState -ne 'idle') {
  $form.Text='Xem trước giao diện VietDub (dữ liệu kiểm thử)'
  $sample=@{step=4;state='running';activity='Tải/cài thư viện giọng đọc VieNeu / PyTorch';pending_downloads=@('torch (2.6 GiB)','torchaudio (4.5 MiB)')}
  if ($PreviewState -eq 'download') {
   $sample=@{step=3;state='running';activity='Tải runtime llama.cpp';download_path=$PreviewImage+'.part';total_bytes=5MB}
   $f=[IO.File]::Create([IO.Path]::GetFullPath($sample.download_path)); $f.SetLength(3MB); $f.Dispose()
  } elseif ($PreviewState -eq 'done') { $sample=@{step=7;state='done';activity='Cài đặt hoàn tất'}; $guide.Enabled=$true; $install.Enabled=$false }
  elseif ($PreviewState -eq 'failed') { $sample=@{step=4;state='failed';activity='Cài thư viện giọng đọc';detail='Không tải được thư viện. Kiểm tra mạng rồi bấm Thử lại.'}; $install.Text='Thử lại' }
  ShowInstallProgress $sample
  $status.Text="Downloading torch (2.6GiB)`r`nDownloading torchaudio (4.5MiB)`r`nDownloaded numpy`r`nDownloaded scipy"
  if ($PreviewState -eq 'download') { $status.Text="Đang tải runtime llama.cpp`r`nĐã nhận 3,0 MiB trên tổng 5,0 MiB (dữ liệu kiểm thử)" }
  elseif ($PreviewState -eq 'done') { $status.Text="Đã kiểm thư viện và kết nối bộ xử lý.`r`nINSTALL_OK — dữ liệu kiểm thử giao diện" }
  elseif ($PreviewState -eq 'failed') { $status.Text="Tải thư viện giọng đọc`r`nKhông kết nối được nguồn tải (lỗi kiểm thử)." }
  $status.SelectionStart=$status.Text.Length; $status.SelectionLength=0
  $elapsed.Text='Đã chạy 00:02:15 • Log cập nhật cách đây 3 giây'
  if ($PreviewState -in @('download','packages')) { foreach($c in @($folder,$browse,$asr,$startup,$consent,$install,$close)){$c.Enabled=$false} }
  $form.Refresh(); [Windows.Forms.Application]::DoEvents()
  # Let native ProgressBar painting/animation reach the requested value.
  for ($i=0;$i -lt 12;$i++) { Start-Sleep -Milliseconds 40; [Windows.Forms.Application]::DoEvents() }
 }
 $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
 try {
  $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
  $bitmap.Save([IO.Path]::GetFullPath($PreviewImage),[Drawing.Imaging.ImageFormat]::Png)
  Write-Output "UI_PREVIEW_OK: $PreviewState rendered; default consent and toggle verified; no install started."
 } finally {
  $bitmap.Dispose(); $form.Close()
  if ($PreviewState -eq 'download') { Remove-Item -LiteralPath ([IO.Path]::GetFullPath($PreviewImage+'.part')) -Force }
 }
} else { [void]$form.ShowDialog() }
$form.Dispose()
