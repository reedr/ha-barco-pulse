"""A fake Barco Pulse projector (JSON-RPC over TCP), seeded with real replies."""

from __future__ import annotations

import asyncio
import json
from typing import Any

SOURCES = [
    "HDMI",
    "DisplayPort 1",
    "DisplayPort 2",
    "Dual DisplayPort columns",
    "Dual DisplayPort sequential",
    "HDBaseT",
    "SDI",
    "DVI 1",
    "DVI 2",
    "Dual DVI columns",
    "Dual DVI sequential",
]


def initial_properties() -> dict[str, Any]:
    """What the theater projector reported on 2026-09-30."""
    return {
        "system.modelname": "Balder CS",
        "system.serialnumber": "2590392444",
        "system.name": "Balder CS-2590392444",
        "system.firmwareversion": "2.5.2",
        "system.health": "Normal",
        "system.state": "ready",
        "system.targetstate": "ready",
        "illumination.state": "Off",
        "illumination.sources.laser.status": "Off",
        "image.window.main.source": "HDMI",
        "image.connector.hdmi.detectedsignal": {"active": True, "name": "5120x2160@60 Hz"},
        "image.resolution.processing.size": {"pixels": 5120, "lines": 2160},
        "environment.temperature.inlet.value": 22.6,
        "environment.temperature.outlet.value": 28.1,
        "environment.temperature.mainboard.value": 34.5,
    }


class FakeBarco:
    """Serves one projector on 127.0.0.1; ``sleep()``/``wake()`` model eco mode."""

    def __init__(self, pin: int = 1234) -> None:
        self.pin = pin
        self.props = initial_properties()
        self.requests: list[dict] = []
        self.port = 0
        self.split = False  # send replies in small pieces
        self.reverse = False  # reply to a batch out of order
        self._server: asyncio.Server | None = None
        self._clients: list[tuple[asyncio.StreamWriter, set[str]]] = []

    async def start(self, port: int = 0) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", port or self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer, _ in self._clients:
            writer.close()
        self._clients.clear()
        if self._server:
            self._server.close()
            self._server.close_clients()
            await self._server.wait_closed()
            self._server = None

    async def sleep(self) -> None:
        """Go to eco: tell subscribers, then drop off the network."""
        await self.set_props({"system.state": "eco", "system.targetstate": "eco"})
        await asyncio.sleep(0.05)
        await self.stop()

    async def wake(self, state: str = "ready") -> None:
        self.props["system.state"] = state
        self.props["system.targetstate"] = state
        await self.start(self.port)

    async def set_props(self, changes: dict[str, Any]) -> None:
        """Change properties and notify subscribers, all in one message."""
        self.props.update(changes)
        for writer, subs in list(self._clients):
            items = [{k: v} for k, v in changes.items() if k in subs]
            if items:
                await self._send(
                    writer,
                    {"jsonrpc": "2.0", "method": "property.changed", "params": {"property": items}},
                )

    async def _send(self, writer: asyncio.StreamWriter, msg: dict) -> None:
        data = json.dumps(msg).encode()
        if self.split:
            for i in range(0, len(data), 7):
                writer.write(data[i : i + 7])
                await writer.drain()
                await asyncio.sleep(0)
        else:
            writer.write(data)
            await writer.drain()

    def _reply(self, req: dict, subs: set[str]) -> tuple[dict, dict | None]:
        method, params, rid = req.get("method"), req.get("params"), req.get("id")
        ok = lambda result: {"jsonrpc": "2.0", "id": rid, "result": result}
        err = lambda msg: {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": msg}}
        if method == "property.get":
            return ok({p: self.props[p] for p in params["property"] if p in self.props}), None
        if method == "property.subscribe":
            subs.update(params["property"])
            return ok(True), None
        if method == "image.source.list":
            return ok(SOURCES), None
        if method == "authenticate":
            return (ok(True), None) if params.get("code") == self.pin else (err("bad pin"), None)
        if method == "property.set":
            if params["property"] == "image.window.main.source" and params["value"] not in SOURCES:
                return err("bad source"), None
            return ok(True), {params["property"]: params["value"]}
        if method == "system.poweron":
            return ok(None), {
                "system.targetstate": "on",
                "system.state": "on",
                "illumination.state": "On",
                "illumination.sources.laser.status": "On",
            }
        if method == "system.poweroff":
            return ok(None), {
                "system.targetstate": "ready",
                "system.state": "ready",
                "illumination.state": "Off",
                "illumination.sources.laser.status": "Off",
            }
        return err(f"unknown method {method}"), None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        subs: set[str] = set()
        self._clients.append((writer, subs))
        decoder = json.JSONDecoder()
        buf = ""
        try:
            while data := await reader.read(65536):
                buf += data.decode()
                batch = []
                while buf.strip():
                    buf = buf.lstrip()
                    try:
                        req, end = decoder.raw_decode(buf)
                    except json.JSONDecodeError:
                        break
                    buf = buf[end:]
                    self.requests.append(req)
                    batch.append(req)
                replies = [self._reply(r, subs) for r in batch]
                if self.reverse:
                    replies.reverse()
                for reply, changes in replies:
                    await self._send(writer, reply)
                    if changes:
                        await self.set_props(changes)
        except ConnectionError:
            pass
        finally:
            self._clients = [c for c in self._clients if c[0] is not writer]
            writer.close()

    def methods(self) -> list[str]:
        return [r["method"] for r in self.requests]
