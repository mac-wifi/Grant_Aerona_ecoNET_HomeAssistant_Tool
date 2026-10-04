"""Reduced stateful ecoNET HTTP emulator; never connects to a real device."""
import asyncio
import json
from pathlib import Path

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
        self.writes = []
        self.requests = []
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
        if self.mode == "timeout":
            await asyncio.sleep(0.2)
            raise web.HTTPGatewayTimeout()
        if self.mode == "http_error":
            raise web.HTTPServiceUnavailable()
        if self.mode == "malformed_json":
            return web.Response(text="{invalid", content_type="application/json")
        response = {**self.success, "paramName": name, "paramValue": value}
        if self.mode == "name_mismatch":
            response["paramName"] = "SyntheticOtherParameter"
        elif self.mode == "value_mismatch":
            response["paramValue"] = value + 1
        elif self.mode == "non_ok":
            response["result"] = "ERROR"
        elif self.mode == "ok":
            self.guest_change(name, value)
        else:
            raise ValueError(f"Unknown emulator mode: {self.mode}")
        return web.json_response(response)
