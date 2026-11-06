"""Exercise the real updater control flow with isolated network/UI adapters."""
import base64
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

from test_release_packaging import ROOT


def run_update(tmp_path, *, bad_hash=False, traversal=False, cancelled=False):
    home = tmp_path / 'nơi cài thử'
    (home / 'app').mkdir(parents=True)
    (home / 'models').mkdir()
    (home / 'app/install-marker.json').write_text('{"product":"VietDub Local"}', encoding='utf-8')
    (home / 'app/current.txt').write_text('0.1.1-r1234567890', encoding='utf-8')
    model = home / 'models/model.bin'
    model.write_bytes(b'model stays')
    archive = tmp_path / 'release.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('VietDubLocal-0.1.2-win-x64/setup.ps1', '# fixture setup')
        if traversal:
            z.writestr('VietDubLocal-0.1.2-win-x64/../../escape.txt', 'bad')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if bad_hash:
        digest = '0' * 64
    release = [{'draft': False, 'tag_name': 'v0.1.2-preview', 'assets': [{
        'name': 'VietDubLocal-0.1.2-win-x64.zip', 'digest': 'sha256:' + digest,
        'browser_download_url': 'https://github.com/hacong86/VietDubLoca/releases/download/v0.1.2-preview/VietDubLocal-0.1.2-win-x64.zip',
    }]}]
    release_file = tmp_path / 'release.json'
    release_file.write_text(json.dumps(release), encoding='utf-8')
    script = (ROOT / 'packaging/windows/update.ps1').read_text(encoding='utf-8-sig')
    lines = script.splitlines()
    out = []
    skipping = False
    for line in lines:
        if '$releases=Invoke-RestMethod ' in line:
            line = " $releases=@(Get-Content -Raw -Encoding UTF8 -LiteralPath $env:VD_TEST_RELEASE | ConvertFrom-Json)"
        elif '$answer=[Windows.Forms.MessageBox]::Show' in line:
            line = " $answer='No'" if cancelled else " $answer='Yes'"
        elif '$client=New-Object Net.WebClient' in line:
            line = ' Copy-Item -LiteralPath $env:VD_TEST_ZIP -Destination $zip'
            skipping = True
        elif skipping:
            skipping = False
            continue
        elif '$proc=Start-Process ' in line:
            line = " Write-Output ('OPENED_SETUP_HOME=' + $HomeDir); $proc=[pscustomobject]@{ ExitCode=0 }"
        elif '[Windows.Forms.MessageBox]::Show($_.Exception.Message' in line:
            line = " Write-Output ('UPDATE_ERROR=' + $_.Exception.Message)"
        out.append(line)
    code = '& {\n' + '\n'.join(out) + '\n} -HomeDir $env:VD_TEST_HOME'
    encoded = base64.b64encode(code.encode('utf-16-le')).decode('ascii')
    env = {**os.environ, 'VD_TEST_RELEASE': str(release_file), 'VD_TEST_ZIP': str(archive), 'VD_TEST_HOME': str(home)}
    result = subprocess.run(['powershell', '-NoProfile', '-STA', '-EncodedCommand', encoded], env=env, capture_output=True, timeout=30)
    assert model.read_bytes() == b'model stays'
    assert not (tmp_path / 'escape.txt').exists()
    return result


def test_update_opens_setup_for_same_home_without_touching_model(tmp_path):
    r = run_update(tmp_path)
    assert r.returncode == 0 and b'OPENED_SETUP_HOME=' in r.stdout


def test_update_rejects_bad_checksum_and_archive_traversal(tmp_path):
    for name, kwargs in [('hash', {'bad_hash': True}), ('traversal', {'traversal': True})]:
        sub = tmp_path / name
        sub.mkdir()
        r = run_update(sub, **kwargs)
        assert r.returncode != 0 and b'UPDATE_ERROR=' in r.stdout and b'OPENED_SETUP_HOME=' not in r.stdout


def test_update_cancel_does_not_launch_installer(tmp_path):
    r = run_update(tmp_path, cancelled=True)
    assert r.returncode == 0 and b'OPENED_SETUP_HOME=' not in r.stdout
