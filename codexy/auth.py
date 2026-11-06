"""Microsoft Entra bearer authentication using the existing Azure CLI login."""

import asyncio
import json
import math
import os
import shutil
import time
from datetime import datetime

import httpx

from .config import AppConfig


class EntraAuthError(RuntimeError):
    """An actionable authentication failure without token or CLI output."""


class AzureCliTokenProvider:
    def __init__(self, config: AppConfig):
        self.config = config
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def invalidate(self, rejected_token: str):
        # A concurrent request may already have refreshed this token.
        if self._token == rejected_token:
            self._token = None
            self._expires_at = 0.0

    async def get_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires_at - 60:
                return self._token
            cli_command = self.config.get("azure_cli_command", "az")
            # Windows installs az.cmd; CreateProcess does not resolve PATHEXT.
            cli_command = shutil.which(cli_command) or cli_command
            command = [
                cli_command,
                "account",
                "get-access-token",
                "--resource",
                self.config.get("azure_token_resource", "https://cognitiveservices.azure.com/"),
                "--output",
                "json",
                "--only-show-errors",
            ]
            if self.config.get("azure_tenant_id"):
                command.extend(["--tenant", self.config["azure_tenant_id"]])
            if self.config.get("azure_subscription_id"):
                command.extend(["--subscription", self.config["azure_subscription_id"]])
            env = os.environ.copy()
            if self.config.get("azure_config_dir"):
                env["AZURE_CONFIG_DIR"] = os.path.expanduser(self.config["azure_config_dir"])
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                )
            except OSError as exc:
                raise EntraAuthError(
                    "Azure CLI was not found. Install it or set AZURE_CLI_COMMAND in .env, then run az login."
                ) from exc
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self.config.get("timeout") or 60)
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                if process.returncode is None:
                    process.kill()
                await process.communicate()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise EntraAuthError("Azure CLI token request timed out. Run az login and retry.") from None
            if process.returncode:
                raise EntraAuthError("Could not obtain an Entra token. Run az login and check your Azure tenant/subscription.")
            try:
                result = json.loads(stdout)
                token = result["accessToken"]
                expiry = result.get("expires_on")
                if expiry is None:
                    # Older Azure CLI versions return a local-time ISO timestamp.
                    expires_at = datetime.fromisoformat(result["expiresOn"]).timestamp()
                else:
                    expires_at = float(expiry)
                if not isinstance(token, str) or not token.strip() or not math.isfinite(expires_at) or expires_at <= time.time():
                    raise ValueError
            except (ValueError, TypeError, KeyError, AttributeError):
                raise EntraAuthError("Azure CLI returned an invalid or expired token. Run az login and retry.") from None
            self._token = token
            self._expires_at = expires_at
            return token


class EntraBearerAuth(httpx.Auth):
    """Refresh bearer tokens on demand, including once after a 401 response."""

    requires_request_body = True

    def __init__(self, provider: AzureCliTokenProvider):
        self.provider = provider

    async def async_auth_flow(self, request):
        token = await self.provider.get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            await response.aread()
            self.provider.invalidate(token)
            request.headers["Authorization"] = f"Bearer {await self.provider.get_token()}"
            yield request
