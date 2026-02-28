"""REST API client for the ecoNET device."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from aiohttp import BasicAuth, ClientSession, ClientTimeout

from .const import (
    API_BASE_PATH,
    API_EDIT_PARAMS,
    API_MAX_RETRIES,
    API_NEW_PARAM,
    API_REG_PARAMS,
    API_RM_CURR_NEW_PARAM,
    API_RM_NEW_PARAM,
    API_SYS_PARAMS,
    API_TIMEOUT,
    MIN_REQUEST_GAP,
)

_LOGGER = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication fails (HTTP 401)."""


class ApiError(Exception):
    """Raised on non-recoverable API errors."""


class EconetClient:
    """Low-level HTTP client for the ecoNET device REST API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: ClientSession,
    ) -> None:
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        self._host = host.rstrip("/")
        self._session = session
        self._auth = BasicAuth(username, password)
        self._timeout = ClientTimeout(total=API_TIMEOUT)
        self._request_lock = asyncio.Lock()
        self._last_request_at: float = 0.0

    @property
    def host(self) -> str:
        return self._host

    def _url(self, endpoint: str) -> str:
        return f"{self._host}{API_BASE_PATH}/{endpoint}"

    async def _throttled_get(
        self, url: str, params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        """Execute a single GET, serialized and throttled.

        Only one request is in-flight at a time (lock), and at least
        MIN_REQUEST_GAP seconds elapse between consecutive requests.
        Raises AuthError on 401, asyncio.TimeoutError on timeout.
        Returns (status_code, parsed_json_or_None).
        """
        async with self._request_lock:
            gap = MIN_REQUEST_GAP - (time.monotonic() - self._last_request_at)
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                kwargs: dict[str, Any] = {
                    "auth": self._auth,
                    "timeout": self._timeout,
                }
                if params:
                    kwargs["params"] = params
                async with self._session.get(url, **kwargs) as resp:
                    if resp.status == 401:
                        raise AuthError(f"Unauthorized: {url}")
                    if resp.status != 200:
                        return resp.status, None
                    return resp.status, await resp.json()
            finally:
                self._last_request_at = time.monotonic()

    async def get(self, endpoint: str) -> dict[str, Any] | None:
        """GET an endpoint with retries. Returns parsed JSON or None."""
        url = self._url(endpoint)
        for attempt in range(1, API_MAX_RETRIES + 1):
            try:
                status, data = await self._throttled_get(url)
                if data is None:
                    _LOGGER.warning(
                        "HTTP %s from %s (attempt %d/%d)",
                        status, url, attempt, API_MAX_RETRIES,
                    )
                    return None
                return data
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Timeout fetching %s (attempt %d/%d)",
                    url, attempt, API_MAX_RETRIES,
                )
        _LOGGER.error("Failed to fetch %s after %d attempts", url, API_MAX_RETRIES)
        return None

    async def get_with_params(
        self, endpoint: str, params: dict[str, str],
    ) -> dict[str, Any] | None:
        """GET an endpoint with query parameters and retries."""
        url = self._url(endpoint)
        for attempt in range(1, API_MAX_RETRIES + 1):
            try:
                status, data = await self._throttled_get(url, params)
                if data is None:
                    _LOGGER.warning(
                        "HTTP %s from %s (attempt %d/%d)",
                        status, url, attempt, API_MAX_RETRIES,
                    )
                    return None
                return data
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Timeout fetching %s (attempt %d/%d)",
                    url, attempt, API_MAX_RETRIES,
                )
        _LOGGER.error("Failed to fetch %s after %d attempts", url, API_MAX_RETRIES)
        return None


class EconetApi:
    """High-level API for reading and writing ecoNET parameters."""

    def __init__(self, client: EconetClient) -> None:
        self._client = client
        self._uid: str | None = None
        self._controller_id: str | None = None
        self._sw_version: str | None = None

    @property
    def host(self) -> str:
        return self._client.host

    @property
    def uid(self) -> str | None:
        return self._uid

    @property
    def controller_id(self) -> str | None:
        return self._controller_id

    @property
    def sw_version(self) -> str | None:
        return self._sw_version

    async def async_init(self) -> None:
        """Fetch system params to populate device identity."""
        sys_params = await self.fetch_sys_params()
        if sys_params:
            self._uid = sys_params.get("uid")
            self._controller_id = sys_params.get("controllerID")
            self._sw_version = sys_params.get("softVer")

    # --- Read endpoints ---

    async def fetch_reg_params(self) -> dict[str, Any] | None:
        """Fetch live readings (temperatures, performance, state)."""
        return await self._client.get(API_REG_PARAMS)

    async def fetch_edit_params(self) -> dict[str, Any] | None:
        """Fetch all editable parameters with min/max/value."""
        return await self._client.get(API_EDIT_PARAMS)

    async def fetch_sys_params(self) -> dict[str, Any] | None:
        """Fetch system info (controller ID, firmware, alarms, etc.)."""
        return await self._client.get(API_SYS_PARAMS)

    # --- Write endpoints ---

    async def set_param(self, param_name: str, value: float | int) -> bool:
        """Set a parameter by name via /econet/newParam."""
        data = await self._client.get_with_params(
            API_NEW_PARAM,
            {"newParamName": param_name, "newParamValue": str(value)},
        )
        return _check_write_result(data, param_name, value)

    async def set_param_by_index(self, index: str | int, value: float | int) -> bool:
        """Set a parameter by numeric index via /econet/rmNewParam."""
        formatted = int(value) if value == int(value) else value
        data = await self._client.get_with_params(
            API_RM_NEW_PARAM,
            {"newParamIndex": str(index), "newParamValue": str(formatted)},
        )
        return _check_write_result(data, f"index:{index}", value)

    async def set_param_by_key(self, key: str | int, value: float | int) -> bool:
        """Set a parameter by key via /econet/rmCurrNewParam."""
        formatted = int(value) if value == int(value) else value
        data = await self._client.get_with_params(
            API_RM_CURR_NEW_PARAM,
            {"newParamKey": str(key), "newParamValue": str(formatted)},
        )
        return _check_write_result(data, f"key:{key}", value)

    async def test_connection(self) -> bool:
        """Quick connectivity and auth check."""
        try:
            data = await self.fetch_sys_params()
            return data is not None
        except AuthError:
            return False


def _check_write_result(data: dict | None, label: str, value: Any) -> bool:
    if data is None or data.get("result") != "OK":
        _LOGGER.error("Failed to set %s = %s, response: %s", label, value, data)
        return False
    _LOGGER.info("Successfully set %s = %s", label, value)
    return True


async def make_api(
    session: ClientSession, host: str, username: str, password: str
) -> EconetApi:
    """Factory: create and initialise the API client."""
    client = EconetClient(host, username, password, session)
    api = EconetApi(client)
    await api.async_init()
    return api
