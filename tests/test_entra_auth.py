import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from codexy.auth import AzureCliTokenProvider, EntraAuthError, EntraBearerAuth
from codexy.core.agent import Agent


def token_process(token="test-token", expires=None):
    process = Mock(returncode=0)
    process.communicate = AsyncMock(
        return_value=(
            json.dumps(
                {
                    "accessToken": token,
                    "expires_on": expires or time.time() + 3600,
                }
            ).encode(),
            None,
        )
    )
    return process


class TestAzureCliTokenProvider(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_windows_cli_launcher_before_spawning(self):
        launcher = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.CMD"
        with (
            patch("shutil.which", return_value=launcher) as which,
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=token_process()) as spawn,
        ):
            assert await AzureCliTokenProvider({}).get_token() == "test-token"
        which.assert_called_once_with("az")
        assert spawn.call_args.args[:3] == (launcher, "account", "get-access-token")

    async def test_concurrent_requests_share_cached_token_and_account_settings(self):
        provider = AzureCliTokenProvider(
            {
                "azure_cli_command": "custom-az",
                "azure_tenant_id": "tenant",
                "azure_subscription_id": "subscription",
                "azure_config_dir": "/custom/config",
                "azure_token_resource": "https://cognitiveservices.azure.com/",
            }
        )
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=token_process()) as spawn:
            assert await asyncio.gather(provider.get_token(), provider.get_token()) == ["test-token", "test-token"]
        spawn.assert_awaited_once()
        assert spawn.call_args.args[:3] == ("custom-az", "account", "get-access-token")
        assert spawn.call_args.args[-4:] == ("--tenant", "tenant", "--subscription", "subscription")
        assert spawn.call_args.kwargs["env"]["AZURE_CONFIG_DIR"] == "/custom/config"

    async def test_refresh_before_expiry(self):
        provider = AzureCliTokenProvider({})
        provider._token = "old"
        provider._expires_at = time.time() + 30
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=token_process("fresh")) as spawn:
            assert await provider.get_token() == "fresh"
        spawn.assert_awaited_once()

    async def test_bad_cli_output_never_discloses_token(self):
        process = token_process("secret-sentinel", expires=-1)
        provider = AzureCliTokenProvider({})
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process):
            with self.assertRaises(EntraAuthError) as caught:
                await provider.get_token()
        assert "secret-sentinel" not in str(caught.exception)
        assert "az login" in str(caught.exception)

    async def test_missing_cli_is_actionable(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(EntraAuthError, "AZURE_CLI_COMMAND"):
                await AzureCliTokenProvider({}).get_token()

    async def test_signed_out_is_actionable_without_cli_output(self):
        process = token_process("secret-sentinel")
        process.returncode = 1
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process):
            with self.assertRaisesRegex(EntraAuthError, "az login") as caught:
                await AzureCliTokenProvider({}).get_token()
        assert "secret-sentinel" not in str(caught.exception)

    async def test_timeout_kills_cli_process(self):
        process = token_process()
        process.returncode = None
        process.communicate.side_effect = [asyncio.TimeoutError(), (b"", None)]
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process):
            with self.assertRaisesRegex(EntraAuthError, "timed out"):
                await AzureCliTokenProvider({}).get_token()
        process.kill.assert_called_once()


class TestEntraHttpAuth(unittest.IsolatedAsyncioTestCase):
    async def test_replaces_sdk_placeholder_and_refreshes_once_on_401(self):
        provider = Mock()
        provider.get_token = AsyncMock(side_effect=["first", "second"])
        requests = []

        def handler(request):
            requests.append((request.headers["Authorization"], request.content))
            return httpx.Response(401, json={"error": "expired"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=EntraBearerAuth(provider)) as client:
            response = await client.post(
                "https://example.test/openai/v1/chat/completions",
                headers={"Authorization": "Bearer placeholder"},
                json={"model": "deployment"},
            )
        assert response.status_code == 401
        assert [header for header, _ in requests] == ["Bearer first", "Bearer second"]
        assert requests[0][1] == requests[1][1]
        provider.invalidate.assert_called_once_with("first")

    async def test_agent_stream_uses_entra_endpoint_and_deployment_without_api_key(self):
        captured = []

        def handler(request):
            captured.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"Hello","output_index":0,"content_index":0,"item_id":"msg_1","sequence_number":0}\n\n'
                    'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_1","output":[],"status":"completed"},"sequence_number":1}\n\n'
                ),
            )

        config = {
            "auth_mode": "entra",
            "base_url": "https://example.openai.azure.com/openai/v1/",
            "model": "deployment",
            "api_key": None,
        }

        class MockClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(handler), **kwargs)

        with (
            patch("codexy.core.agent.httpx.AsyncClient", MockClient),
            patch.object(AzureCliTokenProvider, "get_token", new_callable=AsyncMock, return_value="entra-test-token"),
        ):
            agent = Agent(config)
            try:
                await agent.initialize()
                events = [event async for event in agent.process_turn_stream("Hi")]
                assert await agent.get_available_models() == ["deployment"]
            finally:
                await agent.close()
        assert len(captured) == 1
        assert str(captured[0].url) == "https://example.openai.azure.com/openai/v1/responses"
        assert captured[0].headers["Authorization"] == "Bearer entra-test-token"
        assert json.loads(captured[0].content)["model"] == "deployment"
        assert [event["type"] for event in events] == ["text_delta", "response_end"]
