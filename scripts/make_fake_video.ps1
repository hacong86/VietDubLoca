# Tạo fixture video tiếng Anh tổng hợp (Windows SAPI, không bản quyền bên thứ ba) + phụ đề mốc chính xác.
# Kết quả: D:\VietDubLocal\e2e\fixtures\fake.mp4, fake.json3.json, fake.srt, sentences.json
param([string]$Out = "D:\VietDubLocal\e2e\fixtures")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Out | Out-Null
Add-Type -AssemblyName System.Speech
$sentences = @(
  "Welcome back. In this lesson we will build a simple character controller in Unity.",
  "Make sure you do not delete the original file before checking the copy.",
  "Open the Inspector and uncheck Apply Root Motion.",
  "If the reference is null, skip this step and show a warning.",
  "You can enable this option, but only after creating a backup.",
  "Set the delay to half a second, not five seconds.",
  "Never paste your API key into a public issue.",
  "The model runs locally after the weights have been downloaded.",
  "Reduce the texture size before trying to reduce the polygon count.",
  "Keep the Rigidbody, but remove the extra collider.",
  "This value is updated once per frame, not once per second.",
  "Do not destroy the object until the animation has finished.",
  "Now press play and watch the character move across the scene.",
  "If it jumps too high, lower the jump force in the Inspector.",
  "That is all for today. Thanks for watching, and see you next time."
)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$pcm = New-Object System.IO.MemoryStream
$cues = @()
$t = 1500                      # 1.5 s im lặng đầu
$gapMs = 1200
$silence = { param($ms) New-Object byte[] ([int](16000 * 2 * $ms / 1000)) }
$b = & $silence $t; $pcm.Write($b, 0, $b.Length)
foreach ($s in $sentences) {
  $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $synth.Rate = 0
  $ms = New-Object System.IO.MemoryStream
  $synth.SetOutputToAudioStream($ms, $fmt)
  $synth.Speak($s)
  $synth.Dispose()
  $bytes = $ms.ToArray()
  $dur = [int]($bytes.Length / 32)            # 16k * 2 byte = 32 byte/ms
  $pcm.Write($bytes, 0, $bytes.Length)
  $cues += [pscustomobject]@{ start_ms = $t; end_ms = $t + $dur; text = $s }
  $t += $dur
  $b = & $silence $gapMs; $pcm.Write($b, 0, $b.Length); $t += $gapMs
}
$raw = Join-Path $Out "fake.pcm"
[System.IO.File]::WriteAllBytes($raw, $pcm.ToArray())
$cues | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 (Join-Path $Out "sentences.json")
# json3 giống YouTube (events/segs)
$events = $cues | ForEach-Object { @{ tStartMs = $_.start_ms; dDurationMs = $_.end_ms - $_.start_ms; segs = @(@{ utf8 = $_.text }) } }
(@{ wireMagic = "pb3"; events = @($events) } | ConvertTo-Json -Depth 6 -Compress) | Out-File -Encoding utf8 (Join-Path $Out "fake.json3.json")
$ff = "D:\hermes\tools\ffmpeg\bin\ffmpeg.exe"   # chỉ gọi dùng
$dur = [math]::Ceiling($t / 1000) + 1
& $ff -y -loglevel error -f s16le -ar 16000 -ac 1 -i $raw -f lavfi -i "testsrc2=size=640x360:rate=25:duration=$dur" -shortest -c:v libx264 -pix_fmt yuv420p -g 25 -c:a aac -b:a 96k -ar 48000 -movflags +faststart (Join-Path $Out "fake.mp4")
Remove-Item $raw
"ok duration_ms=$t cues=$($cues.Count)"
