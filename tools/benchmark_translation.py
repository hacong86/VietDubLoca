#!/usr/bin/env python3
"""Đo request dịch trên llama-server LOCAL; không tải/chạy model thay người dùng.
Python >=3.10, chỉ thư viện chuẩn. Đáp án tham chiếu không đi vào prompt.
Không đo TTFT/VRAM/TTS và không tự chấm chất lượng ngữ nghĩa.
"""
from __future__ import annotations
import argparse, hashlib, http.client, ipaddress, json, math, os, platform
import statistics, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

def local_endpoint(base_url: str) -> tuple[str, int, str]:
    u = urlsplit(base_url)
    if u.scheme != 'http' or u.username or u.password or u.query or u.fragment:
        raise ValueError('Chỉ nhận HTTP loopback không có credentials/query/fragment.')
    try:
        ip = ipaddress.ip_address(u.hostname or '')
    except ValueError as exc:
        raise ValueError('Dùng IP loopback cụ thể, ví dụ 127.0.0.1; không dùng DNS.') from exc
    if not ip.is_loopback:
        raise ValueError('Từ chối endpoint ngoài máy cục bộ.')
    if u.path.rstrip('/') != '/v1':
        raise ValueError('Đường dẫn base URL phải là /v1.')
    return str(ip), u.port or 80, '/v1/chat/completions'

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for n, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError(f'{path.name}:{n}: cần JSON object.')
        rows.append(obj)
    return rows

def make_request(row: dict[str, Any], model: str, profile: dict[str, Any],
                 system_prompt: str) -> tuple[dict[str, Any], dict[str, str]]:
    source, sid = row['source_text'], row['id']
    if not isinstance(source, str) or not source.strip() or len(source) > 16000:
        raise ValueError('source_text rỗng/quá dài/không phải chuỗi.')
    terms = row.get('protected_terms', [])
    if not isinstance(terms, list) or any(not isinstance(t, str) or not t for t in terms):
        raise ValueError('protected_terms phải là danh sách chuỗi không rỗng.')
    mapping: dict[str, str] = {}
    if 'VDTERM_' in source:
        raise ValueError('Nguồn chứa namespace placeholder dự trữ.')
    for term in sorted(set(terms), key=len, reverse=True):
        if term in source:
            placeholder = f'VDTERM_{len(mapping):03d}'
            source = source.replace(term, placeholder)
            mapping[placeholder] = term
    # Deliberate field allowlist: NEVER serialize the complete dataset record to the model.
    user = {'domain': row.get('domain', 'general'),
            'context_before': row.get('context_before', []),
            'context_after': row.get('context_after', []),
            'glossary': [{'protected': key, 'literal': value} for key, value in mapping.items()],
            'segments': [{'segment_id': sid, 'source_text': source}]}
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['translations'],
              'properties': {'translations': {'type': 'array', 'minItems': 1, 'maxItems': 1,
               'items': {'type': 'object', 'additionalProperties': False,
                'required': ['segment_id', 'target_text'], 'properties': {
                 'segment_id': {'type': 'string', 'const': sid},
                 'target_text': {'type': 'string', 'minLength': 1}}}}}}
    request = {'model': model, 'messages': [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': json.dumps(user, ensure_ascii=False)}],
        'stream': False, 'max_tokens': 512,
        'response_format': {'type': 'json_object', 'schema': schema}, **profile}
    return request, mapping

def post_local(base_url: str, api_key: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    host, port, path = local_endpoint(base_url)
    # http.client does not consult HTTP_PROXY and does not follow redirects.
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request('POST', path, body=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key})
        response = conn.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('Phản hồi vượt giới hạn 4 MiB.')
        if response.status != 200:
            # Do not print remote error bodies: they may include secrets or payloads.
            raise RuntimeError(f'HTTP {response.status}; xem log local đã redact.')
        obj = json.loads(raw.decode('utf-8'))
        if not isinstance(obj, dict):
            raise ValueError('Response không phải JSON object.')
        return obj
    finally:
        conn.close()

def parse_response(response: dict[str, Any], request: dict[str, Any],
                   mapping: dict[str, str]) -> tuple[str, list[str]]:
    choice = response['choices'][0]
    message = choice['message']
    flags = []
    if choice.get('finish_reason') == 'length':
        flags.append('TRUNCATED')
    if message.get('reasoning_content') or message.get('reasoning') or message.get('tool_calls'):
        flags.append('REASONING_OR_TOOL_OUTPUT')
    content = message.get('content')
    if not isinstance(content, str):
        raise ValueError('content không phải chuỗi.')
    if '<think>' in content or '</think>' in content:
        flags.append('THINK_TAG')
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or set(parsed) != {'translations'}:
        raise ValueError('Output không khớp object translations.')
    translations = parsed['translations']
    if not isinstance(translations, list) or len(translations) != 1:
        raise ValueError('Sai số lượng câu.')
    unit = translations[0]
    if not isinstance(unit, dict) or set(unit) != {'segment_id', 'target_text'}:
        raise ValueError('Sai keys của câu dịch.')
    expected = json.loads(request['messages'][1]['content'])['segments'][0]
    if unit['segment_id'] != expected['segment_id']:
        flags.append('WRONG_ID')
    text = unit['target_text']
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Bản dịch rỗng/không phải chuỗi.')
    for key, literal in mapping.items():
        if text.count(key) != expected['source_text'].count(key):
            flags.append('PLACEHOLDER_COUNT:' + key)
        text = text.replace(key, literal)
    if 'VDTERM_' in text:
        flags.append('UNKNOWN_PLACEHOLDER')
    return text, flags

def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    a = sorted(values); pos = (len(a) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return a[lo] + (a[hi] - a[lo]) * (pos - lo)

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:8766/v1')
    p.add_argument('--api-key-env', default='VIETDUB_LLM_KEY')
    p.add_argument('--model', required=True)
    p.add_argument('--profile', choices=['qwen_non_thinking', 'gemma_non_thinking',
                   'low_temperature_experiment'], required=True)
    p.add_argument('--dataset', type=Path, default=ROOT/'benchmarks/seed_envi.jsonl')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--split', choices=['dev', 'test', 'all'], default='all')
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--repeats', type=int, default=1)
    p.add_argument('--warmup', type=int, default=2)
    p.add_argument('--timeout', type=float, default=90)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args(argv)
    try:
        local_endpoint(a.base_url)
        if a.repeats < 1 or a.warmup < 0 or a.limit < 0 or a.timeout <= 0:
            raise ValueError('repeats≥1; warmup/limit≥0; timeout>0.')
        rows = [r for r in read_jsonl(a.dataset) if a.split == 'all' or r['split'] == a.split]
        if a.limit:
            rows = rows[:a.limit]
        if not rows or len({r['id'] for r in rows}) != len(rows):
            raise ValueError('Dữ liệu rỗng hoặc trùng mã câu.')
        profiles = json.loads((ROOT/'config/generation-profiles.json').read_text(encoding='utf-8'))
        profile = profiles['profiles'][a.profile]
        system = (ROOT/'prompts/translation_system.vi.txt').read_text(encoding='utf-8')
        requests = [(row, *make_request(row, a.model, profile, system)) for row in rows]
        key = os.environ.get(a.api_key_env, '')
        if not a.dry_run and not key:
            raise ValueError('Chưa đặt biến môi trường chứa khóa server local.')
        if a.out.exists() and any(a.out.iterdir()):
            raise ValueError('Thư mục output đã có dữ liệu; chọn thư mục mới để không ghi đè.')
        a.out.mkdir(parents=True, exist_ok=True)
        metadata = {'created_utc': datetime.now(timezone.utc).isoformat(), 'model_alias': a.model,
            'profile_name': a.profile, 'profile': profile, 'base_url': a.base_url,
            'python': sys.version, 'platform': platform.platform(), 'dataset_sha256':
            hashlib.sha256(a.dataset.read_bytes()).hexdigest(), 'prompt_sha256':
            hashlib.sha256(system.encode()).hexdigest(), 'split': a.split, 'limit': a.limit,
            'repeats': a.repeats, 'warmup': a.warmup, 'dry_run': a.dry_run,
            'model_sha256': None, 'runtime_build': None, 'gpu_measurements': None,
            'note_vi': 'Bổ sung model/runtime/GPU thật vào report; script không đo TTFT/TTS/VRAM hoặc chất lượng.'}
        (a.out/'run.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        if a.dry_run:
            (a.out/'requests.jsonl').write_text(''.join(json.dumps(req, ensure_ascii=False)+'\n'
                for _, req, _ in requests), encoding='utf-8')
            print(f'Đã tạo {len(rows)} request kiểm tra; KHÔNG gọi model.')
            return 0
        for i in range(a.warmup):
            _, req, mapping = requests[i % len(requests)]
            parsed, flags = parse_response(post_local(a.base_url, key, req, a.timeout), req, mapping)
            if flags:
                raise ValueError('Warm-up không qua cấu trúc/thinking: ' + ','.join(flags))
        results = []
        with (a.out/'results.jsonl').open('w', encoding='utf-8') as f:
            for repeat in range(a.repeats):
                for row, req, mapping in requests:
                    start = time.perf_counter()
                    result = {'id': row['id'], 'repeat': repeat, 'model_alias': a.model,
                              'domain': row.get('domain'), 'source_text': row['source_text'],
                              'reference_vi': row.get('reference_vi'), 'reference_status': row.get('reference_status'),
                              'target_text': None, 'valid_structure': False, 'flags': [], 'usage': None}
                    try:
                        response = post_local(a.base_url, key, req, a.timeout)
                        text, flags = parse_response(response, req, mapping)
                        result.update(target_text=text, valid_structure=not flags, flags=flags,
                                      usage=response.get('usage'))
                    except Exception as exc:
                        result['flags'] = ['REQUEST_OR_PARSE_ERROR:' + type(exc).__name__]
                    result['request_complete_ms'] = round((time.perf_counter() - start)*1000, 3)
                    results.append(result)
                    f.write(json.dumps(result, ensure_ascii=False)+'\n'); f.flush()
        successful = [r['request_complete_ms'] for r in results if r['valid_structure']]
        summary = {'total_requests': len(results), 'valid_structure': len(successful),
                   'failed_structure_or_request': len(results)-len(successful),
                   'success_latency_ms_p50': percentile(successful, .5),
                   'success_latency_ms_p95': percentile(successful, .95),
                   'semantic_quality': 'NOT_REVIEWED', 'gpu_tts_concurrency': 'NOT_MEASURED_BY_THIS_TOOL'}
        (a.out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if len(successful) == len(results) else 2
    except (ValueError, KeyError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print('Lỗi: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
