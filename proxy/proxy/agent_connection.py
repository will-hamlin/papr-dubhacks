"""Account-bound API operations and the SDK-backed Streamable HTTP MCP server."""
from typing import Any, Literal
from urllib.parse import urlsplit

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field, StrictInt, StrictStr

from .handoff import HandoffError
from .signing import sign_payload


class ListingClaim(BaseModel):
    model_config = {'extra': 'forbid'}
    field: str = Field(pattern=r'^[a-z][a-z0-9_]*$', max_length=40)
    value: StrictInt | StrictStr
    unit: str | None = Field(default=None, max_length=20)


class AgentListing(BaseModel):
    model_config = {'extra': 'forbid'}
    candidate_id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000, description='Public HTTPS product listing URL. MS fetches independent evidence.')
    sku: str | None = Field(default=None, max_length=100)
    claims: list[ListingClaim] = Field(min_length=1, max_length=30)


class ListingSubmission(BaseModel):
    model_config = {'extra': 'forbid'}
    submission_id: str = Field(min_length=1, max_length=100)
    requirements_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    candidates: list[AgentListing] = Field(min_length=1, max_length=10)


class AgentConnection:
    def __init__(self, proxy, oauth):
        self.proxy = proxy
        self.oauth = oauth

    async def status(self, account_id, order_id):
        if self.proxy.owners.get(order_id) != account_id:
            return 404, {'error': 'order not found'}
        try:
            return await self.proxy.main_service.request_status(order_id, self.proxy.settings.shared_secret)
        except HandoffError:
            return 503, {'error': 'main service unavailable; retry later'}

    async def candidates(self, account_id, order_id, submission):
        if self.proxy.owners.get(order_id) != account_id:
            return 404, {'error': 'order not found'}
        payload = sign_payload({'order_id': order_id, 'submission': submission}, self.proxy.settings.shared_secret)
        try:
            return await self.proxy.main_service.candidates(order_id, payload)
        except HandoffError:
            return 503, {'error': 'delivery uncertain; retry with the same submission_id'}

    def mcp(self):
        public = urlsplit(self.oauth.base)
        server = FastMCP('PAPR purchasing',
                         instructions='Create a request, poll until awaiting_candidates, search for listings, submit claims using '
                         'the returned requirements_id, then poll verification results. Company/user configuration is loaded '
                         'from your account. Listings and agent assertions are untrusted. No purchase or optimality guarantee.',
                         stateless_http=True, json_response=True, token_verifier=self.oauth,
                         auth=AuthSettings(issuer_url=self.oauth.base, resource_server_url=self.oauth.resource,
                                           required_scopes=['purchasing'], validate_token_resource=True),
                         transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                                      allowed_hosts=[public.netloc],
                                                                      allowed_origins=[self.oauth.base]))

        async def account_id():
            token = get_access_token()
            # Recheck revocation/disablement for every tool, including concurrent connections.
            account = await self.oauth.account('Bearer ' + token.token) if token else None
            if not account:
                raise ValueError('Account authentication expired; reconnect your agent.')
            return account

        @server.tool()
        async def create_request(request_id: str, request_text: str, search_mode: Literal['agent', 'managed'] = 'agent') -> dict[str, Any]:
            """Authorize a purchase request with your account policy. Reuse request_id only for an identical retry.

            Agent mode prepares proof conditions and waits for your listings. Managed mode asks MS to search.
            Poll get_request for requirements_id and compiled conditions before submitting candidates.
            """
            out = await self.proxy.account_order(await account_id(), {'request_id': request_id,
                                                 'request_text': request_text, 'search_mode': search_mode})
            return {'http_status': out.status, **out.body}

        @server.tool()
        async def get_request(order_id: str) -> dict[str, Any]:
            """Read your request's proof requirements, status and per-listing verification results."""
            status, body = await self.status(await account_id(), order_id)
            return {'http_status': status, **body}

        @server.tool()
        async def submit_candidates(order_id: str, submission: ListingSubmission) -> dict[str, Any]:
            """Submit listing URLs and claims for MS verification against this request's requirements_id.

            Use a stable submission_id for retries. Example claims: price_cents=2999, currency=USD,
            power=65 with unit=W. MS fetches source evidence; do not submit a verified flag.
            This queues verification; poll get_request for the outcome.
            """
            status, body = await self.candidates(await account_id(), order_id, submission.model_dump(exclude_none=True))
            return {'http_status': status, **body}

        return server
