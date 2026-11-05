"""Installer validation uses the same PowerShell helpers as the actual installation."""
import base64
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / 'packaging/windows/install-common.ps1'


def ps(code):
    encoded = base64.b64encode(("$ErrorActionPreference='Stop'; " + code).encode('utf-16-le')).decode()
    return subprocess.run(['powershell', '-NoProfile', '-EncodedCommand', encoded], capture_output=True, timeout=30)


def quoted(path): return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture
def package(tmp_path):
    pkg = tmp_path / 'gói thử'
    pkg.mkdir()
    spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts/build_release.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    key = json.loads((ROOT / 'config/extension-public-key.json').read_text())['key']
    required = ['install.ps1','install-common.ps1','uninstall.ps1','Setup.cmd','setup.ps1','HUONG-DAN.html',
                'LICENSE','NOTICE','app/LICENSE','app/NOTICE','extension/LICENSE','extension/NOTICE',
                'app/bin/uv.exe','app/requirements/broker.lock.txt','app/requirements/tts.lock.txt',
                'app/requirements/asr.lock.txt','extension/manifest.json']
    files = []
    for name in required:
        p = pkg / name
        p.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({'version': '0.1.1', 'key': key}).encode() if name.endswith('manifest.json') else b'fixture'
        p.write_bytes(data)
        files.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
    manifest = {'name': 'VietDub Local','version':'0.1.1','python_version':'3.11.16',
                'extension_ids':[mod.extension_id(key)],'files':files,
                'llama':{'directory':'pinned-build','server_sha256':'a'*64}}
    (pkg/'release-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return pkg, manifest


def verify(pkg): return ps(f". {quoted(COMMON)}; $null=ReadVerifiedPackage {quoted(pkg)}; 'VERIFIED'")


def test_package_valid_then_corrupt_is_rejected(package):
    pkg, _ = package
    good = verify(pkg)
    assert good.returncode == 0 and b'VERIFIED' in good.stdout
    (pkg/'app/bin/uv.exe').write_bytes(b'tampered')
    assert verify(pkg).returncode != 0


@pytest.mark.parametrize('change', ['missing-required','traversal','wrong-id','wrong-version'])
def test_manifest_invalid_cases(package, change):
    pkg, m = package
    if change == 'missing-required': m['files'] = m['files'][1:]
    if change == 'traversal': m['files'][0]['path'] = '../outside.ps1'
    if change == 'wrong-id': m['extension_ids'] = ['a'*32]
    if change == 'wrong-version': m['version'] = '9.9.9'
    (pkg/'release-manifest.json').write_text(json.dumps(m), encoding='utf-8')
    assert verify(pkg).returncode != 0


def test_home_does_not_overwrite_unrelated_data_and_allows_resume(tmp_path):
    target = tmp_path / 'Dữ liệu [có dấu]'
    target.mkdir()
    unrelated = target / 'keep.txt'
    unrelated.write_text('do not delete')
    command = f". {quoted(COMMON)}; ResolveInstallHome {quoted(target)} {quoted(tmp_path/'package')}"
    assert ps(command).returncode != 0
    assert unrelated.read_text() == 'do not delete'
    (target/'.vietdub-install.json').write_text('{"product":"VietDub Local"}')
    assert ps(command).returncode == 0


def test_native_failure_is_not_reported_as_success(tmp_path):
    code = f". {quoted(COMMON)}; InvokeNativeChecked 'powershell.exe' @('-NoProfile','-Command','exit 7') {quoted(tmp_path/'step.log')} 'fixture'; 'SHOULD_NOT_RUN'"
    result = ps(code)
    assert result.returncode != 0 and b'SHOULD_NOT_RUN' not in result.stdout


def test_runtime_has_no_automatic_borrowed_venv(tmp_path):
    from vietdub.runtime.locate import load
    from vietdub.paths import AppPaths
    rt = load(AppPaths(tmp_path))
    assert rt.tts_python is None and rt.asr_python is None
