# Updates only this installation; downloads the official release into a temporary folder.
param([Parameter(Mandatory=$true)][string]$HomeDir)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.IO.Compression.FileSystem
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$temp=$null
try {
 $HomeDir=[IO.Path]::GetFullPath($HomeDir).TrimEnd('\')
 $marker=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $HomeDir 'app\install-marker.json') | ConvertFrom-Json
 if ($marker.product -ne 'VietDub Local') { throw 'Không tìm thấy bản cài VietDub hợp lệ.' }
 $current=([IO.File]::ReadAllText((Join-Path $HomeDir 'app\current.txt'))).Trim()
 if ($current -notmatch '^(\d+\.\d+\.\d+)(?:-r[0-9a-f]+)?$') { throw 'Không đọc được phiên bản đang cài.' }
 $installed=[version]$matches[1]
 Write-Host 'Đang kiểm tra phiên bản trên GitHub...'
 $releases=Invoke-RestMethod -Uri 'https://api.github.com/repos/hacong86/VietDubLoca/releases?per_page=100' -Headers @{'User-Agent'='VietDubLocal-Updater'; 'Accept'='application/vnd.github+json'} -TimeoutSec 30
 $candidates=@(foreach ($release in $releases) {
  if (-not $release.draft -and $release.tag_name -match '^v(\d+\.\d+\.\d+)(?:-preview)?$') {
   [pscustomobject]@{ version=[version]$matches[1]; release=$release }
  }
 }) | Sort-Object version -Descending
 $candidate=$candidates | Select-Object -First 1
 if (-not $candidate) { throw 'Không tìm thấy bản phát hành phù hợp.' }
 if ($candidate.version -le $installed) {
  [Windows.Forms.MessageBox]::Show('Bạn đang dùng phiên bản mới nhất.', 'VietDub Local') | Out-Null
  exit 0
 }
 $version=$candidate.version.ToString()
 $name="VietDubLocal-$version-win-x64.zip"
 $asset=@($candidate.release.assets | Where-Object { $_.name -eq $name })
 if ($asset.Count -ne 1 -or $asset[0].digest -notmatch '^sha256:([a-fA-F0-9]{64})$') { throw 'Bản phát hành thiếu mã kiểm tra SHA-256.' }
 $expected=$matches[1].ToLowerInvariant()
 $url=$asset[0].browser_download_url
 if ($url -ne "https://github.com/hacong86/VietDubLoca/releases/download/$($candidate.release.tag_name)/$name") { throw 'Địa chỉ tệp cập nhật không hợp lệ.' }
 $answer=[Windows.Forms.MessageBox]::Show("Có bản $version. Tải và mở trình cập nhật?`nModel đã tải được giữ lại.", 'Cập nhật VietDub', 'YesNo', 'Question')
 if ($answer -ne 'Yes') { exit 0 }
 $temp=Join-Path ([IO.Path]::GetTempPath()) ('VietDub-update-'+[Guid]::NewGuid().ToString('N'))
 New-Item -ItemType Directory -Path $temp | Out-Null
 $zip=Join-Path $temp $name
 Write-Host "Đang tải bản $version. Xin chờ..."
 $client=New-Object Net.WebClient
 try { $client.Headers.Add('User-Agent','VietDubLocal-Updater'); $client.DownloadFile($url,$zip) } finally { $client.Dispose() }
 if ((Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLowerInvariant() -ne $expected) { throw 'Tệp tải về không khớp mã kiểm tra. Hãy thử lại.' }
 $archive=[IO.Compression.ZipFile]::OpenRead($zip)
 try {
  foreach ($entry in $archive.Entries) {
   $parts=$entry.FullName -split '[/\\]'
   if ($entry.FullName.StartsWith('/') -or $entry.FullName.StartsWith('\') -or $entry.FullName.Contains(':') -or $parts -contains '..' -or $parts[0] -ne "VietDubLocal-$version-win-x64") { throw 'Gói cập nhật có đường dẫn không hợp lệ.' }
  }
 } finally { $archive.Dispose() }
 Write-Host 'Đang chuẩn bị bộ cài...'
 [IO.Compression.ZipFile]::ExtractToDirectory($zip,$temp)
 $setup=Join-Path $temp "VietDubLocal-$version-win-x64\setup.ps1"
 if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Gói cập nhật thiếu bộ cài.' }
 # The setup window verifies the package again and starts installation only when clicked.
 $proc=Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',('"'+$setup+'"'),'-ExistingHome',('"'+$HomeDir+'"')) -PassThru -Wait
 if ($proc.ExitCode -ne 0) { throw 'Không mở được bộ cài. Hãy thử lại.' }
} catch {
 [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Không cập nhật được VietDub', 'OK', 'Error') | Out-Null
 exit 1
} finally {
 if ($temp -and (Test-Path -LiteralPath $temp)) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}
