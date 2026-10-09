"""Reduced stateful ecoNET HTTP emulator; never connects to a real device."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

FIXTURES = Path(__file__).parent / "fixtures"


class EconetEmulator:
    """Sample-shaped state, isolated per test; writes use names, not indices."""

    def __init__(self):
        self.reg = self._load("reg_params")
        self.edit = self._load("edit_params")
        self.sys = self._load("sys_params")
        self.success = self._load("newparam_success")
        self.mode = "ok"
        self.write_modes = []  # optional per-attempt responses for timeout recovery
        self.writes = []
        self.requests = []
        self.timeout_releases = []
        self.client_attempts = []
        self.client_completions = []
        self.app = web.Application()
        self.app.router.add_get("/econet/{endpoint}", self.handle)

    @staticmethod
    def _load(name):
        return json.loads((FIXTURES / f"{name}.json").read_text())

    def guest_change(self, name, value):
        """Simulate an external controller change without an HTTP write."""
        param = next(p for p in self.edit["data"].values() if p["name"] == name)
        param["value"] = value
        self.reg["settingsVer"] += 1
        self.sys["settingsVer"] = self.reg["settingsVer"]

    def session(self, session):
        """Real HTTP with body timeouts armed only after server receipt.

        Tiny total deadlines can cancel before loopback dispatch. Timeout modes
        send headers but withhold JSON; only then time out the real body read.
        Normal requests retain the production client's total timeout.
        """
        @asynccontextmanager
        async def get(*args, **kwargs):
            self.client_attempts.append((args[0], kwargs.get("params")))
            release = None
            try:
                async with session.get(*args, **kwargs) as response:
                    marker = response.headers.get("X-Emulator-Lost-Body")
                    if marker is None:
                        yield response
                    else:
                        release = self.timeout_releases[int(marker)]

                        async def json_body():
                            async with asyncio.timeout(0):
                                return await response.json()

                        yield SimpleNamespace(status=response.status, json=json_body)
            finally:
                if release is not None:
                    release.set()
                self.client_completions.append(len(self.client_attempts))

        return SimpleNamespace(get=get)

    async def handle(self, request):
        endpoint = request.match_info["endpoint"]
        self.requests.append(endpoint)
        if endpoint in ("regParams", "editParams", "sysParams"):
            return web.json_response({"regParams": self.reg, "editParams": self.edit,
                                      "sysParams": self.sys}[endpoint])
        if endpoint != "newParam":
            raise web.HTTPNotFound()
        name = request.query["newParamName"]
        value = float(request.query["newParamValue"])
        self.writes.append((name, value))
        mode = self.write_modes.pop(0) if self.write_modes else self.mode
        if mode in ("timeout", "applied_timeout"):
            if mode == "applied_timeout":
                self.guest_change(name, value)
            release = asyncio.Event()
            index = len(self.timeout_releases)
            self.timeout_releases.append(release)
            response = web.StreamResponse(headers={
                "Content-Type": "application/json", "X-Emulator-Lost-Body": str(index),
            })
            await response.prepare(request)
            await release.wait()
            return response
        if mode == "http_error":
            raise web.HTTPServiceUnavailable()
        if mode == "malformed_json":
            return web.Response(text="{invalid", content_type="application/json")
        response = {**self.success, "paramName": name, "paramValue": value}
        if mode == "name_mismatch":
            response["paramName"] = "SyntheticOtherParameter"
        elif mode == "value_mismatch":
            response["paramValue"] = value + 1
        elif mode == "non_ok":
            response["result"] = "ERROR"
        elif mode == "ok":
            self.guest_change(name, value)
        else:
            raise ValueError(f"Unknown emulator mode: {mode}")
        return web.json_response(response)
