"""Run the complete local verification demo, with isolated data and no paid services by default."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from configure import read_env, service_environment

ROOT = Path(__file__).resolve().parent.parent


def request(url, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url, data=data, headers=headers), timeout=10) as response:
        return json.load(response)


def wait_ready(url, processes):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError('A demo service exited. Inspect main-service/var/verifier-demo/logs.')
        try:
            return request(url)
        except OSError:
            time.sleep(0.25)
    raise RuntimeError('Demo startup timed out. Inspect main-service/var/verifier-demo/logs.')


def smoke(proxy_url, token):
    company = json.loads((ROOT / 'demo/configs/companies/northstar.json').read_text())
    profiles = [json.loads(path.read_text()) for path in (ROOT / 'demo/configs/users').glob('*.json')]
    user = next(p for p in profiles if p['companyId'] == company['companyId'] and p.get('purchasingEnabled', True))
    cases = [('managed', '65W USB-C charger under $40'), ('managed', 'laptop with at least 32 GB RAM under $1000'),
             ('agent', '65W USB-C charger under $40')]
    for mode, text in cases:
        receipt = request(proxy_url + '/orders', {
            'request': {'id': str(uuid4()), 'text': text, 'search_mode': mode,
                        'createdAt': datetime.now(timezone.utc).isoformat()},
            'userConfig': user, 'companyConfig': company}, token)
        if not receipt.get('ok'):
            raise RuntimeError('Smoke request was not accepted.')
        endpoint = proxy_url + '/orders/' + receipt['order_id']
        access = receipt['request_token']
        deadline = time.monotonic() + 60
        submitted = False
        while time.monotonic() < deadline:
            record = request(endpoint, token=access)
            if record['status'] == 'awaiting_candidates' and not submitted:
                request(endpoint + '/candidates', {'submission_id': 'smoke-batch',
                        'requirements_id': record['result']['requirements_id'], 'candidates': [{
                            'candidate_id': 'charger-65', 'sku': 'DEMO-CH65',
                            'url': 'https://catalog.papr.example/charger-65',
                            'claims': [{'field': 'power', 'value': 65, 'unit': 'W'}]}]}, access)
                submitted = True
            if record['status'] in ('completed', 'verification_complete'):
                reports = record['result']['verification']['candidates']
                statuses = [item['formal_proof']['status'] for item in reports]
                expected = ['proven', 'rejected', 'rejected'] if mode == 'managed' else ['proven']
                if statuses != expected or any(item['purchase_authorized'] for item in reports):
                    raise RuntimeError(f'Unexpected {mode} verification result: {statuses}')
                print(f'PASS {mode}: {text} -> {", ".join(statuses)}', flush=True)
                break
            if record['status'] in ('failed', 'interrupted', 'rejected'):
                raise RuntimeError(f'Smoke request ended as {record["status"]}.')
            time.sleep(0.25)
        else:
            raise RuntimeError('Verification did not finish before the smoke-test deadline.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-port', type=int, default=3100)
    parser.add_argument('--proxy-port', type=int, default=8200)
    parser.add_argument('--service-port', type=int, default=8201)
    parser.add_argument('--env-file', type=Path, help='Optional private provider settings; never printed')
    parser.add_argument('--parser', choices=('rules', 'claude'), default='rules')
    parser.add_argument('--smoke', action='store_true', help='Verify both request paths, then stop all three services')
    args = parser.parse_args()
    processes, logs = [], []
    try:
        missing = [name for name in ('fastapi', 'uvicorn', 'httpx', 'pydantic', 'mcp', 'anthropic', 'z3')
                   if importlib.util.find_spec(name) is None]
        if missing or not shutil.which('node'):
            raise RuntimeError('Install proxy and main-service requirements and Node.js first. Missing: ' + ', '.join(missing))
        ports = (args.web_port, args.proxy_port, args.service_port)
        if len(set(ports)) != 3 or any(not 1024 <= port <= 65535 for port in ports):
            raise RuntimeError('Use three distinct ports between 1024 and 65535.')
        for port in ports:
            with socket.socket() as listener:
                try:
                    listener.bind(('127.0.0.1', port))
                except OSError:
                    raise RuntimeError(f'Port {port} is already in use. Choose another port; existing services were not stopped.') from None
        supplied = read_env(args.env_file) if args.env_file else {}
        if args.parser == 'claude' and not (supplied.get('ANTHROPIC_API_KEY') or supplied.get('ANTHROPIC_AUTH_TOKEN')):
            raise RuntimeError('--parser claude requires --env-file with an Anthropic credential and model.')
        if args.parser == 'claude' and not supplied.get('ANTHROPIC_MODEL'):
            raise RuntimeError('Set an explicit ANTHROPIC_MODEL in the private provider settings.')
        secret_path = ROOT / 'secrets/verifier-demo.env'
        if not secret_path.exists():
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            with secret_path.open('x', encoding='utf-8') as handle:
                handle.write(f'PROXY_SHARED_SECRET={secrets.token_urlsafe(48)}\nPROXY_API_TOKEN={secrets.token_urlsafe(48)}\n')
        credentials = read_env(secret_path)
        stack_id = f'{args.proxy_port}-{args.service_port}'
        data = ROOT / 'main-service/var/verifier-demo' / stack_id
        log_dir = data / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        proxy_url = f'http://127.0.0.1:{args.proxy_port}'
        ms_url = f'http://127.0.0.1:{args.service_port}'
        web_url = f'http://127.0.0.1:{args.web_port}'
        env = {**os.environ, **supplied, **credentials, 'PAPR_ENV': 'development', 'PAPR_DEMO_MODE': '1',
               'PROXY_ALLOW_LEGACY_CONFIG': '1', 'PROXY_DYNAMIC_REGISTRATION': '0',
               'SPEC_PARSER': args.parser, 'SPEC_ALLOW_RULE_FALLBACK': '0', 'ENGINE_KIND': 'stub', 'ENGINE_URL': '',
               'MS_DATABASE': str(data / 'requests.sqlite3'), 'PROXY_VAR_DIR': str(ROOT / 'proxy/var/verifier-demo' / stack_id),
               'PROXY_PUBLIC_URL': proxy_url, 'MAIN_SERVICE_URL': ms_url}
        if args.parser == 'rules':
            for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
                env.pop(key, None)
        commands = [
            ('main-service', [sys.executable, '-m', 'uvicorn', '--factory', 'main_service.demo_app:create_app',
                              '--host', '127.0.0.1', '--port', str(args.service_port)], service_environment(env, 'main-service')),
            ('proxy', [sys.executable, '-m', 'uvicorn', '--factory', 'proxy.app:create_app',
                       '--host', '127.0.0.1', '--port', str(args.proxy_port)], service_environment(env, 'proxy')),
            ('web', [shutil.which('node'), str(ROOT / 'demo/server.mjs')],
             {**{key: value for key, value in os.environ.items() if key not in supplied and key not in credentials},
              'PORT': str(args.web_port), 'ORDER_SERVICE_URL': proxy_url + '/orders',
              'ORDER_SERVICE_TOKEN': credentials['PROXY_API_TOKEN']}),
        ]
        for name, command, environment in commands:
            log_file = (log_dir / f'{name}.log').open('w', encoding='utf-8')
            logs.append(log_file)
            processes.append(subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log_file, stderr=log_file,
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        health = wait_ready(ms_url + '/health', processes)
        wait_ready(proxy_url + '/health', processes)
        wait_ready(web_url + '/api/profiles', processes)
        print(f'Demo ready: {web_url}\nParser: {health["parser"]} | Proofs: {health["formal_verifier"]}\n'
              'Fictional supplier evidence. No purchases. Ctrl+C stops this stack.', flush=True)
        if args.smoke:
            smoke(proxy_url, credentials['PROXY_API_TOKEN'])
            return 0
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError('A demo service stopped. Inspect the demo logs.')
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Demo could not complete: {exc}', file=sys.stderr)
        return 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log_file in logs:
            log_file.close()


if __name__ == '__main__':
    raise SystemExit(main())
