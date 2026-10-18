"""Browser account login and OAuth authorization-code flow for public PKCE clients."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from mcp.server.auth.provider import AccessToken
from starlette.concurrency import run_in_threadpool

from .accounts import digest

SCOPE = 'purchasing'
SESSION_COOKIE = 'papr_session'
CSRF_COOKIE = 'papr_login_csrf'
log = logging.getLogger(__name__)
# Preserve Origin on same-origin browser form POSTs while suppressing cross-origin referrers.
HEADERS = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'same-origin',
           'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
           'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}


def safe_url(url: str, origin_only=False):
    try:
        parsed = urlsplit(url)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        return (len(url) <= 2000 and bool(parsed.hostname) and not parsed.username and not parsed.password
                and not parsed.fragment and not re.search(r'[\s\\]', url)
                and (parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')))
                and (not origin_only or (parsed.path in ('', '/') and not parsed.query)))
    except ValueError:
        return False


def client_config(raw):
    if not isinstance(raw, dict):
        raise ValueError('invalid client metadata')
    redirects = raw.get('redirect_uris')
    name = raw.get('client_name', 'Personal agent')
    if not isinstance(name, str) or not 1 <= len(name) <= 100:
        raise ValueError('client_name must have 1 to 100 characters')
    if not isinstance(redirects, list) or not 1 <= len(redirects) <= 10 or any(
            not isinstance(url, str) or not safe_url(url) for url in redirects):
        raise ValueError('redirect URIs must use HTTPS or HTTP loopback, without fragments or credentials')
    if raw.get('token_endpoint_auth_method', 'none') != 'none':
        raise ValueError('public PKCE clients must use token_endpoint_auth_method=none')
    grants = raw.get('grant_types', ['authorization_code', 'refresh_token'])
    if (not isinstance(grants, list) or not all(isinstance(value, str) for value in grants)
            or 'authorization_code' not in grants or not set(grants) <= {'authorization_code', 'refresh_token'}
            or len(grants) != len(set(grants))):
        raise ValueError('unsupported grant types')
    if raw.get('response_types', ['code']) != ['code'] or raw.get('scope', SCOPE) != SCOPE:
        raise ValueError('unsupported response type or scope')
    return {'client_name': name, 'redirect_uris': redirects, 'token_endpoint_auth_method': 'none',
            'grant_types': grants,
            'response_types': ['code'], 'scope': SCOPE}


def page(title, body, status=200):
    return HTMLResponse(f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)} · PAPR</title>
<style>body{{font:16px system-ui;background:#f5f5f1;color:#212b25;max-width:480px;margin:7vh auto;padding:24px}}
main{{background:white;border:1px solid #ddd;border-radius:12px;padding:32px}}label{{display:block;margin-top:18px}}
input{{display:block;box-sizing:border-box;width:100%;padding:10px;margin-top:6px}}button{{padding:11px 18px;margin:22px 8px 0 0;cursor:pointer}}
small{{overflow-wrap:anywhere;color:#555}}a{{color:#245a42}}</style><main><small>PAPR ACCOUNT</small>
<h1>{html.escape(title)}</h1>{body}</main></html>''', status_code=status, headers=HEADERS)


class OAuth:
    def __init__(self, proxy):
        self.proxy = proxy
        self.store = proxy.accounts
        self.base = proxy.settings.public_url.rstrip('/')
        if not safe_url(self.base, origin_only=True):
            raise ValueError('PROXY_PUBLIC_URL must be an HTTPS origin (HTTP loopback is allowed for local development)')
        self.resource = self.base + '/mcp'
        self.secure = self.base.startswith('https:')

    def error(self, error, description, status=400):
        return JSONResponse({'error': error, 'error_description': description}, status_code=status, headers=HEADERS)

    def unauthorized(self):
        return JSONResponse({'error': 'account authentication required'}, status_code=401, headers={
            **HEADERS, 'WWW-Authenticate': f'Bearer resource_metadata="{self.base}/.well-known/oauth-protected-resource/mcp", scope="{SCOPE}"'})

    async def verify_token(self, token: str):
        data = self.store.get(token, 'access')
        if not data or data['resource'] != self.resource or not self.store.profile(data['account_id']):
            return None
        return AccessToken(token=token, client_id=data['client_id'], subject=data['account_id'],
                           scopes=data['scope'].split(), resource=data['resource'], expires_at=int(data['_expires']))

    async def account(self, authorization: str | None):
        if not authorization or not authorization.lower().startswith('bearer '):
            return None
        token = await self.verify_token(authorization[7:])
        return token.subject if token and SCOPE in token.scopes else None

    def session(self, request):
        data = self.store.get(request.cookies.get(SESSION_COOKIE, ''), 'session')
        return data if data and self.store.profile(data['account_id']) else None

    def session_csrf(self, request):
        return hmac.new(self.proxy.settings.shared_secret.encode(),
                        ('session-csrf:' + request.cookies.get(SESSION_COOKIE, '')).encode(), hashlib.sha256).hexdigest()

    def same_origin(self, request):
        origin = request.headers.get('origin')
        return origin is None or origin == self.base

    async def form(self, request):
        # Bound credentials and prevent parameter pollution at OAuth endpoints.
        if len(await request.body()) > 16384:
            raise ValueError('request too large')
        form = await request.form()
        if len(form.multi_items()) != len(form) or any(not isinstance(v, str) for v in form.values()):
            raise ValueError('duplicate or invalid form parameter')
        return dict(form)

    def tokens(self, data, db):
        clean = {k: v for k, v in data.items() if not k.startswith('_')}
        access = self.store.put('access', clean, 900, db)
        result = {'access_token': access, 'token_type': 'Bearer', 'expires_in': 900, 'scope': clean['scope']}
        client = self.store.client(clean['client_id'])
        if client and 'refresh_token' in client['grant_types']:
            result['refresh_token'] = self.store.put('refresh', clean, 30 * 86400, db)
        return JSONResponse(result, headers=HEADERS)

    def register_routes(self, app):
        @app.get('/.well-known/oauth-authorization-server')
        def metadata():
            result = {'issuer': self.base, 'authorization_endpoint': self.base + '/authorize',
                      'token_endpoint': self.base + '/token', 'revocation_endpoint': self.base + '/revoke',
                      'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
                      'token_endpoint_auth_methods_supported': ['none'], 'revocation_endpoint_auth_methods_supported': ['none'],
                      'code_challenge_methods_supported': ['S256'], 'scopes_supported': [SCOPE]}
            if self.proxy.settings.dynamic_registration:
                result['registration_endpoint'] = self.base + '/register'
            return result

        @app.post('/register')
        async def register(request: Request):
            if not self.proxy.settings.dynamic_registration:
                return self.error('registration_not_supported', 'use an operator-registered client', 404)
            if not self.store.rate_limit('register:' + request.client.host, 10):
                return self.error('rate_limited', 'try later', 429)
            try:
                if len(await request.body()) > 16384:
                    raise ValueError('request too large')
                config = client_config(await request.json())
                with self.store.db() as db:
                    if db.execute('SELECT count(*) FROM clients').fetchone()[0] >= 1000:
                        return self.error('registration_limit', 'contact the operator', 429)
                client_id = self.store.save_client(config)
            except ValueError as exc:
                return self.error('invalid_client_metadata', str(exc))
            return JSONResponse({**config, 'client_id': client_id, 'client_id_issued_at': int(self.store.now())},
                                status_code=201, headers=HEADERS)

        @app.get('/authorize')
        async def authorize(request: Request):
            p = dict(request.query_params)
            client = self.store.client(p.get('client_id', ''))
            if len(request.query_params.multi_items()) != len(p) or not client or p.get('redirect_uri') not in client['redirect_uris']:
                return self.error('invalid_request', 'unknown client or unregistered redirect URI')
            # This issuer serves one resource; omission never creates an unbound grant.
            p.setdefault('resource', self.resource)
            if (p.get('response_type') != 'code' or p.get('code_challenge_method') != 'S256'
                    or not re.fullmatch(r'[A-Za-z0-9_-]{43}', p.get('code_challenge', ''))
                    or p.get('resource') != self.resource or p.get('scope', SCOPE) != SCOPE
                    or len(p.get('state', '')) > 2000):
                return self.error('invalid_request', 'code flow requires S256 PKCE, purchasing scope and this MCP resource')
            if not self.store.rate_limit('authorize:' + request.client.host, 60):
                return self.error('rate_limited', 'try later', 429)
            flow = self.store.put('flow', {'oauth': p}, 600)
            return RedirectResponse('/account/login?' + urlencode({'flow': flow}), status_code=303, headers=HEADERS)

        @app.get('/account/login')
        async def login_page(request: Request):
            if not self.store.rate_limit('login-page:' + request.client.host, 60):
                return page('Try again later', 'Wait five minutes before starting sign-in again.', 429)
            flow = request.query_params.get('flow')
            if not flow:
                flow = self.store.put('flow', {}, 600)
            data = self.store.get(flow, 'flow')
            if not data:
                return page('Connection expired', 'Start the connection again in your agent.', 400)
            csrf = secrets.token_urlsafe(32)
            with self.store.db() as db:
                clean = {k: v for k, v in data.items() if not k.startswith('_')}
                clean['csrf'] = digest(csrf)
                db.execute('UPDATE credentials SET data=? WHERE hash=?', (json.dumps(clean), digest(flow)))
            session = self.session(request)
            identity = self.store.profile(session['account_id'])[0] if session else None
            fields = (f'<p>Signed in as <strong>{html.escape(identity.email)}</strong>.</p>' if identity else
                      '<label>Email<input name="email" type="email" required autocomplete="username" maxlength="254"></label>'
                      '<label>Password<input name="password" type="password" required autocomplete="current-password" maxlength="1024"></label>')
            consent = ''
            if data.get('oauth'):
                p = data['oauth']
                client = self.store.client(p['client_id'])
                consent = (f'<p>Connect <strong>{html.escape(client["client_name"])}</strong> to your PAPR account?</p>'
                           '<p>This agent may submit purchase requests and listings, and read your verification results. '
                           'Your company permissions still apply.</p>'
                           f'<small>Returns to {html.escape(p["redirect_uri"])}<br>Client: {html.escape(p["client_id"])}</small>')
            body = (consent + '<form method="post" action="/account/login">'
                    f'<input type="hidden" name="flow" value="{html.escape(flow)}">'
                    f'<input type="hidden" name="csrf" value="{csrf}">{fields}'
                    f'<button name="decision" value="allow">{"Connect agent" if consent else "Sign in"}</button>'
                    '<button name="decision" value="deny" formnovalidate>Cancel</button></form>')
            response = page('Connect your agent' if consent else 'Sign in', body)
            if data.get('oauth'):
                callback = urlsplit(data['oauth']['redirect_uri'])
                callback_origin = callback.scheme + '://' + callback.netloc
                response.headers['Content-Security-Policy'] = HEADERS['Content-Security-Policy'].replace(
                    "form-action 'self'", "form-action 'self' " + callback_origin)
            response.set_cookie(CSRF_COOKIE, csrf, max_age=600, httponly=True, secure=self.secure, samesite='lax', path='/account')
            return response

        @app.post('/account/login')
        async def login(request: Request):
            try:
                form = await self.form(request)
            except ValueError:
                return page('Invalid sign-in', 'Start sign-in again.', 400)
            flow = form.get('flow', '')
            data = self.store.get(flow, 'flow')
            csrf = form.get('csrf', '')
            if (not data or not self.same_origin(request) or not csrf
                    or not hmac.compare_digest(digest(csrf), data.get('csrf', ''))
                    or not hmac.compare_digest(digest(csrf), digest(request.cookies.get(CSRF_COOKIE, '')))):
                log.warning('Sign-in CSRF rejected: flow_valid=%s origin_valid=%s form_token_present=%s '
                            'flow_token_matches=%s cookie_present=%s cookie_matches=%s',
                            bool(data), self.same_origin(request), bool(csrf),
                            bool(data) and hmac.compare_digest(digest(csrf), data.get('csrf', '')),
                            bool(request.cookies.get(CSRF_COOKIE)),
                            hmac.compare_digest(digest(csrf), digest(request.cookies.get(CSRF_COOKIE, ''))))
                return page('Invalid sign-in', 'Start sign-in again.', 400)
            p = data.get('oauth')
            if form.get('decision') == 'deny':
                with self.store.db() as db:
                    self.store.consume(flow, db)
                return self.redirect(p, error='access_denied') if p else RedirectResponse('/account/login', status_code=303)
            if form.get('decision') != 'allow':
                return page('Invalid sign-in', 'Choose whether to connect.', 400)
            session = self.session(request)
            if session:
                account_id = session['account_id']
            else:
                email = form.get('email', '')
                if (not self.store.rate_limit('login-ip:' + request.client.host, 30)
                        or not self.store.rate_limit('login-email:' + email.strip().casefold(), 10)):
                    return page('Try again later', 'Too many sign-in attempts. Wait five minutes.', 429)
                account_id = await run_in_threadpool(self.store.authenticate, email, form.get('password', ''))
                if not account_id:
                    return page('Sign-in failed', '<p>Email or password is incorrect.</p><a href="/account/login?' +
                                urlencode({'flow': flow}) + '">Try again</a>', 401)
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not self.store.consume(flow, db):
                    return page('Connection expired', 'Start sign-in again.', 400)
                old_session = request.cookies.get(SESSION_COOKIE, '')
                self.store.consume(old_session, db)
                browser_token = self.store.put('session', {'account_id': account_id}, 8 * 3600, db)
                if p:
                    code = self.store.put('code', {**p, 'account_id': account_id, 'scope': SCOPE}, 120, db)
                    response = self.redirect(p, code=code)
                else:
                    response = RedirectResponse('/account', status_code=303, headers=HEADERS)
            response.set_cookie(SESSION_COOKIE, browser_token, max_age=8 * 3600, httponly=True,
                                secure=self.secure, samesite='lax', path='/account')
            response.delete_cookie(CSRF_COOKIE, path='/account')
            return response

        @app.get('/account')
        async def account_page(request: Request):
            session = self.session(request)
            if not session:
                return RedirectResponse('/account/login', status_code=303, headers=HEADERS)
            user, company = self.store.profile(session['account_id'])
            csrf = self.session_csrf(request)
            return page('Your account', f'<p>{html.escape(user.name)}<br>{html.escape(user.email)}<br>{html.escape(company.name)}</p>'
                        f'<p>Connect your agent to <small>{html.escape(self.resource)}</small>.</p>'
                        '<p>Your company manages your permissions and spending limits.</p>'
                        f'<form method="post" action="/account/logout"><input type="hidden" name="csrf" value="{csrf}">'
                        '<button name="action" value="logout">Sign out</button>'
                        '<button name="action" value="revoke">Disconnect all agents and sign out</button></form>')

        @app.post('/account/logout')
        async def logout(request: Request):
            try:
                form = await self.form(request)
            except ValueError:
                return self.error('invalid_request', 'invalid form')
            session = self.session(request)
            if not session or not self.same_origin(request) or not hmac.compare_digest(
                    digest(form.get('csrf', '')), digest(self.session_csrf(request))):
                return self.error('invalid_request', 'invalid session or CSRF token', 403)
            if form.get('action') == 'revoke':
                self.store.revoke_account(session['account_id'])
            else:
                with self.store.db() as db:
                    self.store.consume(request.cookies[SESSION_COOKIE], db)
            response = RedirectResponse('/account/login', status_code=303, headers=HEADERS)
            response.delete_cookie(SESSION_COOKIE, path='/account')
            return response

        @app.post('/token')
        async def token(request: Request):
            try:
                f = await self.form(request)
            except ValueError:
                return self.error('invalid_request', 'invalid form')
            if not self.store.rate_limit('token:' + request.client.host, 120):
                return self.error('rate_limited', 'try later', 429)
            client = self.store.client(f.get('client_id', ''))
            if not client:
                return self.error('invalid_client', 'unknown client', 401)
            kind = {'authorization_code': 'code', 'refresh_token': 'refresh'}.get(f.get('grant_type'))
            if not kind or f['grant_type'] not in client['grant_types']:
                return self.error('unsupported_grant_type', 'unsupported grant type')
            f.setdefault('resource', self.resource)
            if f.get('resource') != self.resource:
                return self.error('invalid_target', 'resource must identify this MCP server')
            supplied = f.get('code' if kind == 'code' else 'refresh_token', '')
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                data = self.store.get(supplied, kind, db, include_used=True)
                if not data or data['client_id'] != f['client_id'] or data['resource'] != self.resource:
                    return self.error('invalid_grant', 'invalid or expired grant')
                if data['_used']:
                    if kind == 'refresh':
                        self.store.revoke_family(data['family'], db)
                    return self.error('invalid_grant', 'grant already used')
                if not self.store.profile(data['account_id']):
                    return self.error('invalid_grant', 'account unavailable')
                if kind == 'code':
                    verifier = f.get('code_verifier', '')
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                    if (f.get('redirect_uri') != data['redirect_uri'] or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier)
                            or not hmac.compare_digest(challenge, data['code_challenge'])):
                        return self.error('invalid_grant', 'redirect URI or PKCE verification failed')
                    grant = {k: data[k] for k in ('account_id', 'client_id', 'resource', 'scope')}
                    grant['family'] = secrets.token_hex(16)
                else:
                    if f.get('scope', data['scope']) != data['scope']:
                        return self.error('invalid_scope', 'scope cannot change during refresh')
                    grant = data
                    self.store.revoke_family(data['family'], db)
                if not self.store.consume(supplied, db) and kind == 'code':
                    return self.error('invalid_grant', 'grant already used')
                return self.tokens(grant, db)

        @app.post('/revoke')
        async def revoke(request: Request):
            try:
                f = await self.form(request)
            except ValueError:
                return self.error('invalid_request', 'invalid form')
            with self.store.db() as db:
                data = (self.store.get(f.get('token', ''), 'access', db, include_used=True)
                        or self.store.get(f.get('token', ''), 'refresh', db, include_used=True))
                if data and data['client_id'] == f.get('client_id'):
                    self.store.revoke_family(data['family'], db)
            return JSONResponse({}, headers=HEADERS)

    def redirect(self, params, **result):
        parsed = urlsplit(params['redirect_uri'])
        query = parse_qsl(parsed.query) + list(result.items())
        if 'state' in params:
            query.append(('state', params['state']))
        return RedirectResponse(urlunsplit(parsed._replace(query=urlencode(query))), status_code=303, headers=HEADERS)
