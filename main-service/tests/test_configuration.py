"""Configuration failures must be explicit and diagnostics must never reveal secrets."""
import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

from main_service.engine import AgentV1Engine, HttpEngine
from main_service.spec import ClaudeSpecParser, FallbackSpecParser, RuleSpecParser, make_parser

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('papr_configuration', ROOT / 'scripts' / 'configure.py')
configuration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configuration)


@pytest.fixture
def clean_env(monkeypatch):
    for name in ('PAPR_ENV', 'SPEC_PARSER', 'SPEC_ALLOW_RULE_FALLBACK', 'ANTHROPIC_API_KEY',
                 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL', 'VP_AGENT_KEY', 'ENGINE_AGENT_KEY',
                 'ENGINE_API_KEY', 'VP_PROXY_MODE', 'ENGINE_MODE'):
        monkeypatch.delenv(name, raising=False)


def test_initialize_private_config_exclusively(tmp_path):
    path = tmp_path / '.env.local'
    configuration.init_env(path, 'development')
    values = configuration.read_env(path)
    assert len(values['PROXY_SHARED_SECRET']) >= 32
    assert values['PROXY_SHARED_SECRET'] != values['PROXY_API_TOKEN']
    assert configuration.check(values)['ok']
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        configuration.init_env(path, 'development')
    assert path.read_bytes() == before
    if __import__('os').name != 'nt':
        assert path.stat().st_mode & 0o077 == 0


def test_production_template_reports_real_blockers_without_keys(tmp_path):
    path = tmp_path / '.env.production'
    configuration.init_env(path, 'production')
    values = configuration.read_env(path)
    report = configuration.check(values)
    assert not report['ok']
    assert 'Anthropic credential is missing' in report['errors']
    assert any('ENGINE_URL' in error for error in report['errors'])
    assert values['PROXY_SHARED_SECRET'] not in str(report)
    assert values['PROXY_API_TOKEN'] not in str(report)


def production_settings(tmp_path):
    values = configuration.read_env(ROOT / '.env.production.example')
    values.update(PROXY_SHARED_SECRET='s' * 64, PROXY_API_TOKEN='a' * 64,
                  PROXY_PUBLIC_URL='https://papr.acme.com', ANTHROPIC_API_KEY='provider-secret',
                  ENGINE_URL='http://127.0.0.1:8002', VP_AGENT_KEY='verifier-secret',
                  MS_SUPPLIER_HOSTS='{"www.supplier.com":"sup_01"}',
                  PROXY_VAR_DIR=str(tmp_path / 'proxy'), MS_DATABASE=str(tmp_path / 'requests.sqlite3'))
    return values


def test_production_configuration_validates_but_does_not_claim_live_readiness(tmp_path):
    report = configuration.check(production_settings(tmp_path))
    assert report['ok']
    assert 'not performed' in report['live_validation']
    assert 'provider-secret' not in str(report)
    assert 'verifier-secret' not in str(report)


@pytest.mark.parametrize('key,value', [
    ('PROXY_ALLOW_LEGACY_CONFIG', '1'), ('SPEC_PARSER', 'rules'),
    ('SPEC_ALLOW_RULE_FALLBACK', '1'), ('ENGINE_KIND', 'stub'),
    ('VP_AGENT_KEY', 'vpk_pbapo_dev_only'), ('MS_SUPPLIER_HOSTS', '{}'),
    ('ENGINE_URL', 'http://remote.acme.com'), ('ENGINE_URL', 'https://user:secret@remote.acme.com'),
    ('PROXY_PUBLIC_URL', 'http://127.0.0.1:8000'), ('PROXY_PUBLIC_URL', 'https://app.example'),
    ('MAIN_SERVICE_URL', 'https://remote.acme.com'), ('ENGINE_POLL_S', 'nan'),
    ('VP_PROXY_MODE', 'autonomous'), ('ANTHROPIC_MODEL', '<bad model>'),
])
def test_production_rejects_unsafe_or_missing_settings(tmp_path, key, value):
    values = production_settings(tmp_path)
    values[key] = value
    assert not configuration.check(values)['ok']


def test_environment_file_is_literal_not_shell(tmp_path):
    path = tmp_path / '.env'
    path.write_text("PROXY_API_TOKEN='$(do-not-execute)'\nMS_SUPPLIER_HOSTS={\"a.com\":\"s\"}\n", encoding='utf-8')
    assert configuration.read_env(path)['PROXY_API_TOKEN'] == '$(do-not-execute)'
    path.write_text('PROXY_API_TOKEN=x\nPROXY_API_TOKEN=y\n', encoding='utf-8')
    with pytest.raises(ValueError):
        configuration.read_env(path)


def test_parser_modes_and_credential_fail_closed(clean_env, monkeypatch):
    assert isinstance(make_parser(), RuleSpecParser)
    with pytest.raises(RuntimeError, match='SPEC_PARSER'):
        make_parser('typo')
    with pytest.raises(RuntimeError, match='requires ANTHROPIC'):
        make_parser('claude')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-provider-key')
    monkeypatch.setenv('ANTHROPIC_MODEL', 'claude-sonnet-5-5')
    monkeypatch.setenv('PAPR_ENV', 'production')
    parser = make_parser('claude')
    assert isinstance(parser, ClaudeSpecParser)
    assert parser.model == 'claude-sonnet-5-5'
    asyncio.run(parser.client.close())
    monkeypatch.setenv('PAPR_ENV', 'development')
    parser = make_parser('claude')
    assert isinstance(parser, FallbackSpecParser)
    asyncio.run(parser.primary.client.close())


def test_live_backend_requires_key_and_http_adapter_sends_configured_bearer(clean_env, monkeypatch):
    with pytest.raises(RuntimeError, match='VP_AGENT_KEY'):
        AgentV1Engine('http://127.0.0.1:8002')
    monkeypatch.setenv('ENGINE_API_KEY', 'configured-backend-token')
    received = []
    async def exercise():
        engine = HttpEngine('http://engine.test', transport=httpx.MockTransport(
            lambda request: received.append(request.headers['Authorization']) or httpx.Response(200, json={})))
        await engine.search({})
        await engine.aclose()
    asyncio.run(exercise())
    assert received == ['Bearer configured-backend-token']


def test_backend_error_body_does_not_leak_secrets(clean_env):
    async def exercise():
        engine = AgentV1Engine('http://engine.test', api_key='private', transport=httpx.MockTransport(
            lambda request: httpx.Response(403, text='your private credential is private')))
        from main_service.engine import EngineError
        with pytest.raises(EngineError) as exc:
            await engine.search({})
        assert str(exc.value) == 'engine returned HTTP 403'
        await engine.aclose()
    asyncio.run(exercise())


def test_launcher_limits_credentials_to_the_service_that_uses_them(tmp_path):
    values = production_settings(tmp_path)
    proxy = configuration.service_environment(values, 'proxy')
    ms = configuration.service_environment(values, 'main-service')
    assert 'ANTHROPIC_API_KEY' not in proxy and 'VP_AGENT_KEY' not in proxy
    assert 'PROXY_API_TOKEN' not in ms
    assert proxy['PROXY_SHARED_SECRET'] == ms['PROXY_SHARED_SECRET']
    assert values['ANTHROPIC_API_KEY'] == 'provider-secret'


def test_direct_production_startup_refuses_development_modes(clean_env, monkeypatch, tmp_path):
    from main_service.service import MainService, Settings
    from proxy.service import Proxy, Settings as ProxySettings
    monkeypatch.setenv('PAPR_ENV', 'production')
    with pytest.raises(RuntimeError, match='explicit live'):
        MainService(Settings(shared_secret='s' * 64, database=tmp_path / 'ms.sqlite3'))
    with pytest.raises(RuntimeError, match='legacy|LEGACY'):
        Proxy(ProxySettings(shared_secret='s' * 64, api_token='a' * 64,
                            public_url='https://papr.acme.com', allow_legacy_config=True))
