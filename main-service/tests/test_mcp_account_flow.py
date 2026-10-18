"""The official MCP client discovers OAuth, signs in, and submits independently verified listings."""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata

from main_service.app import create_app as create_ms
from main_service.engine import StubEngine
from main_service.service import Settings as MSSettings
from main_service.spec import RuleSpecParser
from main_service.verification import ListingVerifier
from proxy.app import create_app
from proxy.handoff import MainServiceClient
from proxy.service import Settings
from .test_candidates import Pages, candidate


class ClientStorage:
    tokens = None
    client_info = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        self.client_info = client_info


def test_official_mcp_oauth_client_to_ms_verification(tmp_path):
    async def run():
        pages = Pages()
        engine = StubEngine()
        ms_app = create_ms(MSSettings(shared_secret='sdk-test', database=tmp_path / 'ms.sqlite3'),
                           RuleSpecParser(), engine, ListingVerifier(pages, {'supplier.example': 'sup_01'}))
        ms = ms_app.state.service
        bridge = MainServiceClient('http://ms.test', transport=httpx.ASGITransport(app=ms_app))
        base = 'http://127.0.0.1:8000'
        app = create_app(Settings(shared_secret='sdk-test', var_dir=tmp_path / 'proxy',
                                  public_url=base, dynamic_registration=True), bridge)
        store = app.state.proxy.accounts
        data = Path(__file__).resolve().parents[2] / 'proxy' / 'data'
        store.company(json.loads((data / 'company_policy.json').read_text()))
        user = json.loads((data / 'users.json').read_text())[0]
        store.create_account('acme', user, 'an integration-test password')
        storage = ClientStorage()
        callback = []
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url=base) as browser:
            async def redirect_handler(url):
                # Simulate the human's browser; credentials never enter the agent's token storage.
                page = await browser.get(url, follow_redirects=True)
                assert page.status_code == 200, page.text
                fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)">', page.text))
                response = await browser.post('/account/login', data={**fields, 'email': user['email'],
                                              'password': 'an integration-test password', 'decision': 'allow'})
                assert response.status_code == 303, response.text
                query = parse_qs(urlsplit(response.headers['location']).query)
                callback.append((query['code'][0], query.get('state', [None])[0]))

            async def callback_handler():
                return callback.pop()

            oauth = OAuthClientProvider(server_url=base + '/mcp', storage=storage,
                                        client_metadata=OAuthClientMetadata(
                                            client_name='Official SDK test', redirect_uris=['https://agent.example/callback'],
                                            grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
                                            token_endpoint_auth_method='none'),
                                        redirect_handler=redirect_handler, callback_handler=callback_handler)
            async with httpx.AsyncClient(transport=transport, auth=oauth, follow_redirects=True) as http:
                async with streamable_http_client(base + '/mcp', http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert len(tools.tools) == 3 and storage.tokens.refresh_token
                        created = await session.call_tool('create_request', {'request_id': 'sdk-flow',
                                                          'request_text': '65W USB-C charger under $40'})
                        assert not created.isError, created
                        order_id = created.structuredContent['order_id']
                        assert await ms.process_next()
                        result = (await session.call_tool('get_request', {'order_id': order_id})).structuredContent
                        assert result['status'] == 'awaiting_candidates' and 'handoff' not in result
                        batch = {'submission_id': 'sdk-batch', 'requirements_id': result['result']['requirements_id'],
                                 'candidates': [candidate()]}
                        submitted = await session.call_tool('submit_candidates', {'order_id': order_id, 'submission': batch})
                        assert not submitted.isError and submitted.structuredContent['http_status'] == 202
                        assert await ms.process_next()
                        verified = (await session.call_tool('get_request', {'order_id': order_id})).structuredContent
                        assert verified['status'] == 'verification_complete'
                        assert verified['result']['verification']['candidates'][0]['claims_status'] == 'supported'
                        proof = verified['result']['verification']['candidates'][0]['formal_proof']
                        assert proof['status'] == 'proven'
                        assert proof['requirements_id'] == batch['requirements_id']
                        assert proof['purchase_authorized'] is False
                        repeated = await session.call_tool('submit_candidates', {'order_id': order_id, 'submission': batch})
                        assert repeated.structuredContent['duplicate'] is True
                        assert len(pages.calls) == 1 and engine.received == []
                        # The client uses its saved refresh token when its local access expiry elapses.
                        oauth.context.token_expiry_time = 1
                        previous_refresh = storage.tokens.refresh_token
                        await session.list_tools()
                        assert storage.tokens.refresh_token != previous_refresh
                        assert storage.client_info.client_id
        stored = ms.store.get(order_id)
        assert stored['handoff']['user']['id'] == user['id']
        assert stored['handoff']['authorization']['identity_verified'] is True
    asyncio.run(run())
