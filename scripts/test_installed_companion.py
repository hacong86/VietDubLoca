"""Smoke test an ISOLATED install. Never uses registry, user browser or model weights.

python scripts/test_installed_companion.py --home <workspace>/.local/<install>
Uses the installed .cmd (including Unicode path), native framing, real tray/broker,
authentication and first-run status. Secrets stay in memory; only checks are printed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import struct
import subprocess
import time
import urllib.error
import urllib.request


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--home', type=Path, required=True)
    home = p.parse_args().home.resolve()
    owned = Path(__file__).resolve().parents[1] / '.local'
    if not home.is_relative_to(owned.resolve()) or home == owned.resolve():
        raise ValueError('Test install must be within this checkout/.local')
    version = (home / 'app/current.txt').read_text('utf-8').strip()
    app = home / 'app' / version
    cfg = json.loads((home / 'local-config.json').read_text('utf-8-sig'))
    origin = f"chrome-extension://{cfg['allowed_extension_ids'][0]}"
    cmd = home / 'runtime/native/vietdub-native-host.cmd'
    proc = subprocess.Popen([os.environ['COMSPEC'], '/d', '/c', str(cmd), origin + '/'],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            cwd=home, creationflags=0x08000000)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    def read():
        header = proc.stdout.read(4)
        assert len(header) == 4, 'No native response (launcher failed)'
        n, = struct.unpack('=I', header)
        assert n < 65536
        return json.loads(proc.stdout.read(n))
    def exchange(body):
        data = json.dumps(body).encode()
        proc.stdin.write(struct.pack('=I', len(data)) + data)
        proc.stdin.flush()
        return pool.submit(read).result(timeout=100)
    checks = []
    try:
        hello = exchange({'type':'hello', 'protocol_version':1})
        expected = json.loads((owned.parent / 'package.json').read_text('utf-8'))['version']
        assert hello['compatible'] and hello['app_version'] == expected, hello
        checks.append('native .cmd at Unicode path; hello version ' + expected)
        paired = exchange({'type':'start'})
        assert paired.get('type') == 'paired', paired.get('code', 'not paired')
        checks.append('native start launches real installed companion and pairs')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(paired['broker_url'] + '/v1/setup', headers={
            'Authorization':'Bearer ' + paired['session_token'], 'Origin':origin})
        with opener.open(req, timeout=10) as r:
            s = json.load(r)
        assert not s['ready'] and not s['busy'] and s['asr_runtime_available']
        assert len(s['models']) == 4 and all(m['state'] == 'not_downloaded' for m in s['models'])
        checks.append('authenticated first-run status: missing weights, own ASR available')
        try:
            opener.open(paired['broker_url'] + '/v1/setup', timeout=5)
            raise AssertionError('Anonymous setup must fail')
        except urllib.error.HTTPError as e:
            assert e.code == 401
        checks.append('unauthenticated setup rejected')
        assert exchange({'type':'stop_owned_processes'})['type'] == 'stopped'
        time.sleep(2)
        assert not exchange({'type':'status'})['running']
        checks.append('own broker shuts down')
        result = {'result':'PASS', 'version':hello['app_version'], 'checks':checks,
                  'limits':'No registry/Chrome native registration or AI weights/inference tested'}
        (owned / 'installed-companion-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
        print('INSTALLED_COMPANION_COMPLETE PASS: ' + '; '.join(checks))
    finally:
        proc.kill()
        proc.wait(timeout=5)
        # Close only tray/broker processes of this isolated install, by executable prefix.
        literal = str(app).replace("'", "''") + '\\'
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
                  f"$_.ExecutablePath.StartsWith('{literal}',[StringComparison]::OrdinalIgnoreCase) -and "
                  "$_.CommandLine -like '*vietdub*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
        subprocess.run(['powershell', '-NoProfile', '-Command', script], check=True, capture_output=True)
        pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
