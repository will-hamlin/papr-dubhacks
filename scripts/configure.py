"""Generate private settings, check them without exposing values, and launch one service."""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SECRET_NAMES = ('PROXY_SHARED_SECRET', 'PROXY_API_TOKEN', 'ANTHROPIC_API_KEY',
                'ANTHROPIC_AUTH_TOKEN', 'VP_AGENT_KEY', 'ENGINE_AGENT_KEY', 'ENGINE_API_KEY')


def read_env(path: Path) -> dict[str, str]:
    """Read literal KEY=value lines. Never execute shell syntax or expand variables."""
    values = {}
    for number, raw in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key.strip()):
            raise ValueError(f'Invalid environment assignment at line {number}')
        key, value = key.strip(), value.strip()
        if key in values:
            raise ValueError(f'Duplicate environment variable at line {number}')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed quote at line {number}')
            value = value[1:-1]
        values[key] = value
    return values


def init_env(path: Path, profile: str) -> None:
    template = ROOT / ('.env.production.example' if profile == 'production' else '.env.example')
    text = template.read_text(encoding='utf-8')
    for key in ('PROXY_SHARED_SECRET', 'PROXY_API_TOKEN'):
        text = text.replace(f'{key}=\n', f'{key}={secrets.token_urlsafe(48)}\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental rotation of secrets for existing databases/sessions.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def loopback(host: str | None) -> bool:
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host or '').is_loopback
    except ValueError:
        return False


def safe_url(value: str, *, public=False, internal=False) -> bool:
    try:
        url = urlsplit(value)
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            return False
        if url.port == 0:
            return False
        if url.scheme not in ('https', 'http'):
            return False
        if url.scheme == 'http' and not loopback(url.hostname):
            return False
        if internal and not loopback(url.hostname):
            return False
        if public:
            if url.scheme != 'https' or loopback(url.hostname) or url.path not in ('', '/'):
                return False
            if url.hostname.endswith(('.example', '.invalid', '.test', '.localhost')) or url.hostname == 'example.com':
                return False
        return True
    except ValueError:
        return False


def check(values: dict[str, str], *, full=False) -> dict:
    errors, warnings = [], []
    production = values.get('PAPR_ENV') == 'production' or full
    if values.get('PAPR_ENV', 'development') not in ('development', 'production'):
        errors.append('PAPR_ENV must be development or production')
    for key in ('PROXY_SHARED_SECRET', 'PROXY_API_TOKEN'):
        value = values.get(key, '')
        if len(value) < 32 or value.lower().startswith(('replace', 'change', 'example', 'test', 'dev')):
            errors.append(f'{key} requires a generated secret of at least 32 characters')
    if values.get('PROXY_SHARED_SECRET') == values.get('PROXY_API_TOKEN'):
        errors.append('Application secrets must be distinct')
    for key in SECRET_NAMES:
        if any(character.isspace() for character in values.get(key, '')):
            errors.append(f'{key} must not contain whitespace')
    if not safe_url(values.get('PROXY_PUBLIC_URL', ''), public=production):
        errors.append('PROXY_PUBLIC_URL must be a real HTTPS origin (loopback HTTP permitted only in development)')
    if not safe_url(values.get('MAIN_SERVICE_URL', ''), internal=True):
        errors.append('MAIN_SERVICE_URL must use loopback on this shared server')
    for flag in ('PROXY_ALLOW_LEGACY_CONFIG', 'PROXY_DYNAMIC_REGISTRATION', 'SPEC_ALLOW_RULE_FALLBACK'):
        if values.get(flag, '0') not in ('0', '1'):
            errors.append(f'{flag} must be 0 or 1')
    if production and values.get('PROXY_ALLOW_LEGACY_CONFIG') == '1':
        errors.append('Production forbids caller-supplied legacy company/user configuration')
    parser = values.get('SPEC_PARSER', 'auto')
    has_ai = bool(values.get('ANTHROPIC_API_KEY') or values.get('ANTHROPIC_AUTH_TOKEN'))
    if parser not in ('rules', 'auto', 'claude'):
        errors.append('SPEC_PARSER must be rules, auto, or claude')
    if parser == 'claude' or production:
        if not has_ai:
            errors.append('Anthropic credential is missing')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{1,199}', values.get('ANTHROPIC_MODEL', '')):
            errors.append('ANTHROPIC_MODEL must be an explicit model ID')
    if production and (parser != 'claude' or values.get('SPEC_ALLOW_RULE_FALLBACK', '0') != '0'):
        errors.append('Full production requires Claude parsing with rule fallback disabled')
    if parser == 'rules' or (parser == 'auto' and not has_ai):
        warnings.append('Rules parser is active; natural-language coverage is limited')
    kind, engine_url = values.get('ENGINE_KIND', 'auto'), values.get('ENGINE_URL', '')
    if kind not in ('stub', 'auto', 'http', 'agent_v1'):
        errors.append('ENGINE_KIND is invalid')
    if production and kind not in ('http', 'agent_v1'):
        errors.append('Full production requires an explicit live ENGINE_KIND')
    if kind in ('http', 'agent_v1') or engine_url or production:
        if not safe_url(engine_url):
            errors.append('ENGINE_URL must be HTTPS or loopback HTTP without embedded credentials')
        key = (values.get('VP_AGENT_KEY') or values.get('ENGINE_AGENT_KEY')) if kind != 'http' else values.get('ENGINE_API_KEY')
        if not key or key == 'vpk_pbapo_dev_only':
            errors.append('Verifier bearer credential is missing or still the old development default')
    else:
        warnings.append('Stub backend is active; managed search and formal verification are unavailable')
    if values.get('VP_PROXY_MODE', values.get('ENGINE_MODE', 'supervised')) != 'supervised':
        errors.append('This configuration supports supervised backend mode only; purchasing is not enabled')
    try:
        poll = float(values.get('ENGINE_POLL_S', '0'))
        if not math.isfinite(poll) or not 0 <= poll <= 300:
            raise ValueError
    except ValueError:
        errors.append('ENGINE_POLL_S must be a finite number from 0 to 300')
    try:
        hosts = json.loads(values.get('MS_SUPPLIER_HOSTS', '{}'))
        if not isinstance(hosts, dict) or not all(isinstance(host, str) and isinstance(supplier, str)
                and re.fullmatch(r'[a-z0-9.-]+', host) and '.' in host and supplier
                for host, supplier in hosts.items()):
            raise ValueError
        if production and not hosts:
            errors.append('MS_SUPPLIER_HOSTS must map real supplier hostnames to account policy supplier IDs')
    except (ValueError, TypeError):
        errors.append('MS_SUPPLIER_HOSTS must be a JSON object of exact lowercase hostnames to supplier IDs')
    if production:
        for key in ('PROXY_VAR_DIR', 'MS_DATABASE'):
            if not values.get(key) or not Path(values[key]).is_absolute():
                errors.append(f'{key} must be an absolute persistent path on this deployment host')
    return {'ok': not errors, 'profile': 'production' if production else 'development',
            'credentials': {key: 'set' if values.get(key) else 'missing' for key in SECRET_NAMES},
            'errors': errors, 'warnings': warnings,
            'live_validation': 'not performed; account/client provisioning, provider access, backend compatibility, DNS and TLS still require smoke tests'}


def service_environment(values: dict[str, str], component: str) -> dict[str, str]:
    result = dict(values)
    excluded = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'VP_AGENT_KEY', 'ENGINE_AGENT_KEY', 'ENGINE_API_KEY') \
        if component == 'proxy' else ('PROXY_API_TOKEN',)
    for name in excluded:
        result.pop(name, None)
    result['PYTHONPATH'] = str(ROOT / component)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'check', 'run'))
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.local')
    parser.add_argument('--profile', choices=('development', 'production'), default='development', help='init profile')
    parser.add_argument('--full', action='store_true', help='require full production settings during check')
    parser.add_argument('--service', choices=('proxy', 'main-service'))
    parser.add_argument('--demo', action='store_true', help='use fictional supplier catalog for local MS demo')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            init_env(args.env_file, args.profile)
            print('Created private settings with two distinct application secrets. External credentials remain unset.')
            return 0
        # Explicit file values win, including blanks: inherited credentials cannot mask missing setup.
        values = {**os.environ, **read_env(args.env_file)}
        if args.demo and (args.command != 'run' or args.service != 'main-service'
                          or values.get('PAPR_ENV', 'development') != 'development' or args.full):
            parser.error('--demo requires run --service main-service in development')
        report = check(values, full=args.full)
        if args.demo:
            report['effective_engine'] = 'demo_fixture'
            report['warnings'] = [message for message in report['warnings'] if not message.startswith('Stub backend')]
            report['warnings'].append('Demo supplier evidence is fictional; no live search, formal proof, or purchase')
        print(json.dumps(report, indent=2))
        if not report['ok']:
            return 1
        if args.command == 'check':
            return 0
        if not args.service:
            parser.error('run requires --service')
        component = args.service
        module, port = ('proxy', '8000') if component == 'proxy' else ('main_service', '8001')
        # Import from this checkout; preserve persistent paths independently of the working directory.
        values = service_environment(values, component)
        factory = f'{module}.app:create_app'
        if args.demo:
            values['PAPR_DEMO_MODE'] = '1'
            factory = 'main_service.demo_app:create_app'
        command = [sys.executable, '-m', 'uvicorn', '--factory', factory,
                   '--host', '127.0.0.1', '--port', port, '--workers', '1']
        return subprocess.call(command, cwd=ROOT, env=values)
    except (OSError, ValueError):
        # Never echo file contents, command-line secrets, or exception messages containing them.
        print('Configuration operation failed: check file permissions, syntax, and whether the output already exists.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
