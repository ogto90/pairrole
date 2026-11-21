"""Offline behavioral checks for the six November 2026 Dependabot findings.

Run with the hash-verified security tool environment, not the application venv.
Private SDK helpers are intentional: these canaries validate the pinned override.
"""
import asyncio
import subprocess
import sys
from types import SimpleNamespace

import httpx
from pydantic import AnyHttpUrl
from mcp import ClientSession, types
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.utils import credentials_match_issuer, validate_metadata_issuer
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared._httpx_utils import request_within_origin


async def check_mcp():
    # #1: bounded session admission and immediate reclamation.
    manager = StreamableHTTPSessionManager(Server('canary'), max_sessions=1)
    first = manager._admit_session(None)
    assert first is not None and manager.session_idle_timeout == 1800
    assert manager._admit_session(None) is None
    await manager._discard_session(first.mcp_session_id, first)
    assert not manager._server_instances
    print('#1: session capacity and reclamation passed')

    # #3: external schema references fail; document-local references work.
    session = ClientSession(None, None)
    result = types.CallToolResult(content=[], structuredContent={'value': 1})
    for reference in ('https://example.invalid/schema', 'file:///nonexistent-schema'):
        session._tool_output_schemas['canary'] = {'$ref': reference}
        try:
            await session._validate_tool_result('canary', result)
        except RuntimeError as exc:
            assert 'Invalid schema' in str(exc)
        else:
            raise AssertionError('External schema reference accepted')
    session._tool_output_schemas['canary'] = {
        '$defs': {'result': {'type': 'object'}}, '$ref': '#/$defs/result'}
    await session._validate_tool_result('canary', result)
    print('#3: external and local schema reference checks passed')

    # #4: even an explicitly redirect-following client must not leak a POST.
    for target, expected in [('https://other.invalid/', 1), ('/safe', 2)]:
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(307, headers={'location': target}) if len(seen) == 1 else httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            await request_within_origin(client, 'POST', 'https://trusted.invalid/',
                                        headers={'X-API-Key': 'canary'}, content=b'private')
        assert len(seen) == expected
    print('#4: cross-origin redirect rejection and same-origin support passed')

    # #5: the audience check rejects a token for another resource.
    backend = BearerAuthBackend(None, resource_server_url=AnyHttpUrl('https://trusted.invalid/'))
    assert backend._issued_for_this_resource('https://trusted.invalid/')
    assert not backend._issued_for_this_resource('https://other.invalid/')
    assert not backend._issued_for_this_resource(None)
    print('#5: token audience checks passed')

    # #7: metadata and stored credential issuers must match.
    metadata = SimpleNamespace(issuer='https://trusted.invalid/')
    validate_metadata_issuer(metadata, 'https://trusted.invalid/')
    try:
        validate_metadata_issuer(metadata, 'https://other.invalid/')
    except OAuthFlowError:
        pass
    else:
        raise AssertionError('Mismatched issuer accepted')
    credentials = SimpleNamespace(issuer='https://trusted.invalid/', client_id='canary')
    assert credentials_match_issuer(credentials, 'https://trusted.invalid/', None)
    assert not credentials_match_issuer(credentials, 'https://other.invalid/', None)
    print('#7: metadata and credential issuer binding passed')


if __name__ == '__main__':
    asyncio.run(check_mcp())
    # #8: kill a regressed matcher rather than blocking CI for minutes.
    subprocess.run([sys.executable, '-c', """
from wcmatch import fnmatch, glob
assert not fnmatch.fnmatch('_' * 255, '*_*_*_*_*.csv')
assert not glob.globmatch('uploads/' + '_' * 255, 'uploads/*_*_*_*_*.csv')
assert fnmatch.fnmatch('a_b_c_d_e.csv', '*_*_*_*_*.csv')
assert glob.globmatch('uploads/a_b_c_d_e.csv', 'uploads/*_*_*_*_*.csv')
"""], check=True, timeout=5)
    print('#8: multi-star matching rejects adversarial names within five seconds')
