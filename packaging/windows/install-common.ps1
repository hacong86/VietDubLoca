# Shared by the real installer, preflight and regression tests. PowerShell 5.1.
function WriteText([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding $false))
}
function Sha([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
function ChildPath([string]$Root, [string]$Relative) {
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ([IO.Path]::IsPathRooted($Relative)) { throw 'Không chấp nhận đường dẫn tuyệt đối trong gói.' }
    $p = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $p.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Đường dẫn vượt khỏi thư mục đã chọn.' }
    $cursor = $p
    while ($cursor -and $cursor.Length -ge $base.Length) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Thư mục cài đặt không được chứa junction/symlink.'
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $p
}
function ResolveInstallHome([string]$Path, [string]$PackageRoot) {
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\')) { throw 'Hãy chọn đường dẫn tuyệt đối trên ổ đĩa máy này.' }
    $p = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($p -match '[%&!^\r\n"]') { throw 'Đường dẫn không được chứa %, &, !, ^ hoặc dấu nháy.' }
    if ($p.Length -lt 4 -or $p.Length -gt 160) { throw 'Chọn thư mục con có đường dẫn ngắn hơn 160 ký tự, không chọn gốc ổ đĩa.' }
    $pkg = [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\')
    if ($p -eq $pkg -or $p.StartsWith($pkg+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Chọn nơi cài khác thư mục gói vừa giải nén.' }
    foreach ($protected in @($env:WINDIR, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:USERPROFILE)) {
        if ($protected -and ($p -eq $protected -or ($protected -ne $env:USERPROFILE -and $p.StartsWith($protected+'\',[StringComparison]::OrdinalIgnoreCase)))) {
            throw 'Không cài vào thư mục hệ thống hoặc gốc thư mục tài khoản.'
        }
    }
    $null = ChildPath $p 'app'
    if (Test-Path -LiteralPath $p) {
        $marker = Join-Path $p 'app\install-marker.json'
        $resume = Join-Path $p '.vietdub-install.json'
        if (@(Get-ChildItem -LiteralPath $p -Force).Count -gt 0 -and -not (Test-Path -LiteralPath $marker) -and -not (Test-Path -LiteralPath $resume)) {
            throw 'Thư mục đã có dữ liệu khác. Chọn thư mục trống hoặc bản cài VietDub bằng bộ cài này.'
        }
        foreach ($mark in @($marker,$resume)) {
            if ((Test-Path -LiteralPath $mark) -and ((Get-Content -Raw -Encoding UTF8 -LiteralPath $mark | ConvertFrom-Json).product -ne 'VietDub Local')) { throw 'Dấu cài đặt không hợp lệ.' }
        }
    }
    return $p
}
function ReadVerifiedPackage([string]$Root) {
    $m = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Root 'release-manifest.json') | ConvertFrom-Json
    if ($m.name -ne 'VietDub Local' -or $m.version -notmatch '^\d+\.\d+\.\d+$' -or $m.python_version -notmatch '^3\.\d+\.\d+$') { throw 'Manifest không hợp lệ.' }
    if (@($m.extension_ids).Count -ne 1 -or $m.extension_ids[0] -notmatch '^[a-p]{32}$') { throw 'ID tiện ích không hợp lệ.' }
    if ($m.llama.directory -notmatch '^[a-zA-Z0-9._-]+$' -or $m.llama.server_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Runtime ghim không hợp lệ.' }
    $seen = @{}
    foreach ($f in $m.files) {
        if ($seen.ContainsKey($f.path) -or $f.sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Danh sách checksum không hợp lệ.' }
        $seen[$f.path] = $true
        $p = ChildPath $Root $f.path
        if (-not (Test-Path -LiteralPath $p -PathType Leaf) -or (Sha $p) -ne $f.sha256) { throw "Gói hỏng hoặc bị sửa: $($f.path). Hãy giải nén lại bản tải chính thức." }
    }
    foreach ($required in @('install.ps1','install-common.ps1','uninstall.ps1','Setup.cmd','setup.ps1','HUONG-DAN.html','LICENSE','NOTICE','app/LICENSE','app/NOTICE','extension/LICENSE','extension/NOTICE','app/bin/uv.exe','app/requirements/broker.lock.txt','app/requirements/tts.lock.txt','app/requirements/asr.lock.txt','extension/manifest.json')) {
        if (-not $seen.ContainsKey($required)) { throw "Thiếu thành phần bắt buộc: $required" }
    }
    $ext = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Root 'extension\manifest.json') | ConvertFrom-Json
    $hash = [Security.Cryptography.SHA256]::Create().ComputeHash([Convert]::FromBase64String($ext.key))
    $id = -join ($hash[0..15] | ForEach-Object { [char](97 + ($_ -shr 4)); [char](97 + ($_ -band 15)) })
    if ($id -ne $m.extension_ids[0] -or $ext.version -ne $m.version) { throw 'Tiện ích và bộ cài không cùng bản/ID.' }
    return $m
}
function InvokeNativeChecked([string]$Exe, [string[]]$Arguments, [string]$LogPath, [string]$Step) {
    Write-Host "[VietDub] $Step"
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Add-Content -Encoding UTF8 -LiteralPath $LogPath -Value "$_" }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $old }
    if ($code -ne 0) { throw "$Step thất bại (mã $code). Xem $LogPath. Có thể chạy lại Setup.cmd để tiếp tục." }
}
