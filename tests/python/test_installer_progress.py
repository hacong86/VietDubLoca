"""Real PowerShell child processes, log streaming, and determinate progress rules."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from test_release_packaging import COMMON, ps, quoted


@pytest.mark.parametrize('code', [0, 7])
def test_gui_child_exit_code_survives_polling(tmp_path, code):
    child=base64.b64encode(f"Write-Output 'child output'; exit {code}".encode('utf-16-le')).decode()
    script=f"""
    . {quoted(COMMON)}
    $p=StartInstallerProcess '{child}' {quoted(tmp_path/'out.log')} {quoted(tmp_path/'err.log')}
    $deadline=(Get-Date).AddSeconds(15)
    do {{ Start-Sleep -Milliseconds 80; $p.Refresh(); if((Get-Date) -gt $deadline){{throw 'Timeout'}} }} while(-not $p.HasExited)
    $p.WaitForExit(); @{{code=$p.ExitCode}} | ConvertTo-Json -Compress; $p.Dispose()
    """
    result=ps(script)
    assert result.returncode==0, result.stderr.decode(errors='replace')
    assert json.loads(result.stdout)['code']==code


def test_progress_percentage_is_only_measured_from_file(tmp_path):
    partial=tmp_path/'payload.part';partial.write_bytes(b'x'*512)
    result=ps(f""". {quoted(COMMON)}
    $known=InstallProgressView @{{step=3;state='running';activity='download';download_path={quoted(partial)};total_bytes=1024}}
    $unknown=InstallProgressView @{{step=4;state='running';activity='packages';pending_downloads=@('torch (2.6 GiB)')}}
    $done=InstallProgressView @{{step=7;state='done';activity='done'}}
    $failed=InstallProgressView @{{step=4;state='failed';activity='failure';detail='network'}}
    @{{known=$known;unknown=$unknown;done=$done;failed=$failed}} | ConvertTo-Json -Depth 5 -Compress
    """)
    assert result.returncode==0
    d=json.loads(result.stdout.decode('utf-8-sig'))
    assert d['known']['percent']==50 and d['known']['completed']==2
    assert d['unknown']['percent'] is None and 'torch' in d['unknown']['detail']
    assert d['done']['completed']==7 and d['done']['percent']==100
    assert d['failed']['completed']==3 and d['failed']['percent'] is None


def test_native_download_events_are_visible_before_completion(tmp_path):
    snapshot=tmp_path/'progress.json';live=tmp_path/'live.log';log=tmp_path/'full.log'
    child=tmp_path/'child.ps1'
    child.write_text("Write-Output 'Downloading torch (2.6GiB)'\nWrite-Output 'Downloading numpy (15MiB)'\nStart-Sleep -Milliseconds 1200\nWrite-Output 'Downloaded numpy'\nStart-Sleep -Milliseconds 1200\nWrite-Output 'Downloaded torch'\nexit 0\n",'utf-8')
    script=f"""$ErrorActionPreference='Stop'; . {quoted(COMMON)}
    StartInstallProgress {quoted(snapshot)} {quoted(live)}
    $script:InstallProgress.step=4
    InvokeNativeChecked 'powershell.exe' @('-NoProfile','-File',{quoted(child)}) {quoted(log)} 'Download packages'
    """
    encoded=base64.b64encode(script.encode('utf-16-le')).decode()
    proc=subprocess.Popen(['powershell','-NoProfile','-EncodedCommand',encoded],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    seen=[];deadline=time.monotonic()+20
    try:
        while proc.poll() is None:
            assert time.monotonic()<deadline
            if snapshot.exists():
                try:seen.append(json.loads(snapshot.read_text('utf-8-sig'))['pending_downloads'])
                except (OSError,ValueError):pass
            time.sleep(.05)
        stdout,stderr=proc.communicate(timeout=2)
        assert proc.returncode==0,stderr.decode(errors='replace')
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=5)
    assert any(len(x)==2 for x in seen)
    assert any(x==['torch (2.6GiB)'] for x in seen)
    assert json.loads(snapshot.read_text('utf-8-sig'))['pending_downloads']==[]
    assert 'Downloaded torch' in live.read_text('utf-8-sig')
    tail=ps(f". {quoted(COMMON)}; $s=ReadInstallLogTail {quoted(live)}; [Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($s)))")
    lines=base64.b64decode(tail.stdout).decode('utf-8')
    assert '\r\n' in lines and '\n' not in lines.replace('\r\n','')
