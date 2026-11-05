# Native Windows setup screen. Uses only the Windows .NET Framework.
param([string]$PreviewImage='')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
. (Join-Path $PSScriptRoot 'install-common.ps1')
$script:installProcess=$null; $script:installedHome=$null; $script:stdoutPath=$null
$form=New-Object Windows.Forms.Form
$form.Text='Cài đặt VietDub Local'; $form.ClientSize=New-Object Drawing.Size(720,650)
$form.StartPosition='CenterScreen'; $form.FormBorderStyle='FixedDialog'; $form.MaximizeBox=$false
$form.Font=New-Object Drawing.Font('Segoe UI',10)
$form.BackColor=[Drawing.Color]::White
function LabelAt($Text,$X,$Y,$W,$H) {
 $c=New-Object Windows.Forms.Label; $c.Text=$Text; $c.Location=New-Object Drawing.Point($X,$Y); $c.Size=New-Object Drawing.Size($W,$H); $form.Controls.Add($c); return $c
}
$title=LabelAt 'VietDub Local' 28 22 660 40
$title.Font=New-Object Drawing.Font('Segoe UI',22,[Drawing.FontStyle]::Bold)
$null=LabelAt 'Nghe video YouTube tiếng Anh bằng giọng Việt. AI xử lý ngay trên máy.' 30 72 660 30
$null=LabelAt 'Windows 10/11 x64 · NVIDIA · khuyên dùng RAM 32 GB · ổ trống 20 GB' 30 105 660 30
$null=LabelAt 'Nơi lưu chương trình, mô hình và bộ nhớ đệm' 30 151 660 25
$folder=New-Object Windows.Forms.TextBox; $folder.Location=New-Object Drawing.Point(30,181); $folder.Size=New-Object Drawing.Size(550,28)
$folder.Text=if (Test-Path 'D:\') { 'D:\VietDubLocal' } else { Join-Path $env:LOCALAPPDATA 'VietDubLocal' }; $form.Controls.Add($folder)
$browse=New-Object Windows.Forms.Button; $browse.Text='Chọn...'; $browse.Location=New-Object Drawing.Point(590,178); $browse.Size=New-Object Drawing.Size(100,34); $form.Controls.Add($browse)
$browse.Add_Click({
 $dialog=New-Object Windows.Forms.FolderBrowserDialog; $dialog.Description='Chọn thư mục trống hoặc bản cài VietDub bằng bộ cài này'
 if ($dialog.ShowDialog() -eq 'OK') { $folder.Text=$dialog.SelectedPath }; $dialog.Dispose()
})
function CheckAt($Text,$Y) {
 $c=New-Object Windows.Forms.CheckBox; $c.Text=$Text; $c.Location=New-Object Drawing.Point(30,$Y); $c.Size=New-Object Drawing.Size(660,30); $form.Controls.Add($c); return $c
}
$asr=CheckAt 'Thêm nhận dạng âm thanh cho video không có phụ đề (có thể cài sau)' 228
$startup=CheckAt 'Tự mở VietDub khi đăng nhập Windows' 264
$notice=LabelAt "Lần đầu cần tải vài GB thư viện từ Python/PyPI, PyTorch và GitHub.`r`nMô hình AI tải riêng trong tiện ích, có hiển thị dung lượng và giấy phép.`r`nKhông cần cài Python trước hoặc chạy bằng quyền quản trị." 30 305 660 76
$consent=CheckAt 'Tôi đồng ý tải các thành phần cần thiết để cài đặt.' 390
$status=New-Object Windows.Forms.TextBox; $status.Multiline=$true; $status.ReadOnly=$true; $status.ScrollBars='Vertical'
$status.Location=New-Object Drawing.Point(30,432); $status.Size=New-Object Drawing.Size(660,130)
$status.Text='Chọn nơi lưu, đánh dấu đồng ý rồi bấm Cài đặt.'; $form.Controls.Add($status)
$install=New-Object Windows.Forms.Button; $install.Text='Cài đặt'; $install.Enabled=$false
$install.Location=New-Object Drawing.Point(480,588); $install.Size=New-Object Drawing.Size(120,38); $form.Controls.Add($install)
$close=New-Object Windows.Forms.Button; $close.Text='Đóng'; $close.Location=New-Object Drawing.Point(610,588); $close.Size=New-Object Drawing.Size(80,38); $form.Controls.Add($close)
$guide=New-Object Windows.Forms.Button; $guide.Text='Mở hướng dẫn'; $guide.Location=New-Object Drawing.Point(30,588); $guide.Size=New-Object Drawing.Size(155,38); $guide.Enabled=$false; $form.Controls.Add($guide)
$guide.Add_Click({ if ($script:installedHome) { Start-Process -FilePath (Join-Path $script:installedHome 'HUONG-DAN.html') } })
$close.Add_Click({$form.Close()})
$consent.Add_CheckedChanged({$install.Enabled=$consent.Checked -and -not $script:installProcess})
$timer=New-Object Windows.Forms.Timer; $timer.Interval=700
$timer.Add_Tick({
 if (-not $script:installProcess) { return }
 if (Test-Path -LiteralPath $script:stdoutPath) {
  try { $status.Text=Get-Content -Raw -Encoding UTF8 -LiteralPath $script:stdoutPath; $status.SelectionStart=$status.Text.Length; $status.ScrollToCaret() } catch { }
 }
 $script:installProcess.Refresh()
 if ($script:installProcess.HasExited) {
  $timer.Stop(); $script:installProcess.WaitForExit(); $code=$script:installProcess.ExitCode
  $script:installProcess.Dispose(); $script:installProcess=$null
  foreach ($c in @($folder,$browse,$asr,$startup,$consent,$close)) { $c.Enabled=$true }
  $install.Enabled=$consent.Checked; $install.Text='Thử lại'
  if ($code -eq 0) {
   $status.AppendText("`r`nĐã cài xong. Bấm Mở hướng dẫn để thêm tiện ích vào Chrome.")
   $guide.Enabled=$true; $install.Enabled=$false
  } else { $status.AppendText("`r`nChưa cài xong. Xem lỗi phía trên hoặc logs\install.log trong nơi lưu. Chạy lại để tiếp tục.") }
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
  $script:stdoutPath=Join-Path $logs 'setup-output.log'; $stderr=Join-Path $logs 'setup-error.log'
  $cmd='[Console]::OutputEncoding=[Text.Encoding]::UTF8; & '+(PSLiteral (Join-Path $PSScriptRoot 'install.ps1'))+' -HomeDir '+(PSLiteral $target)+' -AcceptDownloads'
  if ($asr.Checked) { $cmd+=' -IncludeAsr' }; if ($startup.Checked) { $cmd+=' -StartWithWindows' }
  $cmd+='; exit $LASTEXITCODE'
  $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
  $script:installProcess=Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded) -WindowStyle Hidden -RedirectStandardOutput $script:stdoutPath -RedirectStandardError $stderr -PassThru
  $script:installedHome=$target
  foreach ($c in @($folder,$browse,$asr,$startup,$consent,$install,$close,$guide)) { $c.Enabled=$false }
  $status.Text='Đang cài. Có thể mất nhiều phút ở lần đầu; không tắt máy.'; $timer.Start()
 } catch { $status.Text=$_.Exception.Message; $install.Enabled=$consent.Checked }
})
$form.Add_FormClosing({ if ($script:installProcess) { $_.Cancel=$true; $status.AppendText("`r`nĐang cài, vui lòng chờ hoàn tất để tránh làm gián đoạn.") } })
$form.Add_FormClosed({$timer.Stop(); $timer.Dispose()})
if ($PreviewImage) {
 # Render actual WinForms controls for local UI verification; no installation or download.
 $form.Show(); $form.Refresh(); [Windows.Forms.Application]::DoEvents()
 $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
 try {
  $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
  $bitmap.Save([IO.Path]::GetFullPath($PreviewImage),[Drawing.Imaging.ImageFormat]::Png)
  if ($install.Enabled -or $consent.Checked) { throw 'Download consent must be off initially.' }
  $consent.Checked=$true
  if (-not $install.Enabled) { throw 'Consent does not enable Install.' }
  $consent.Checked=$false
  if ($install.Enabled) { throw 'Revoking consent must disable Install.' }
  Write-Output 'UI_PREVIEW_OK: native form rendered; consent toggle verified; no install started.'
 } finally { $bitmap.Dispose(); $form.Close() }
} else { [void]$form.ShowDialog() }
$form.Dispose()
