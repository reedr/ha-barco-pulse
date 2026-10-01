"""JSON-RPC client for Barco Pulse projectors (TCP port 9090).

The projector speaks JSON-RPC 2.0 over a raw TCP stream with no framing, sends
replies out of order, and pushes ``property.changed`` notifications for
subscribed properties. In eco mode it drops off the network and has to be woken
with a wake-on-LAN packet.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import re
import socket
import time
from collections.abc import Callable
from typing import Any

from wakeonlan import send_magic_packet

from . import const

_LOGGER = logging.getLogger(__name__)

SYSTEM_TARGETSTATE = "system.targetstate"
SYSTEM_STATE = "system.state"
SYSTEM_HEALTH = "system.health"
SYSTEM_MODEL = "system.modelname"
SYSTEM_SERIAL = "system.serialnumber"
SYSTEM_NAME = "system.name"
SYSTEM_FIRMWARE = "system.firmwareversion"
INLET_T = "environment.temperature.inlet.value"
OUTLET_T = "environment.temperature.outlet.value"
MAINBOARD_T = "environment.temperature.mainboard.value"
LASER_STATUS = "illumination.sources.laser.status"
ILLUM_STATE = "illumination.state"
HDMI_SIGNAL = "image.connector.hdmi.detectedsignal"
OUTPUT_SIZE = "image.resolution.processing.size"
INPUT_SOURCE = "image.window.main.source"

# Derived values (not projector properties).
SOURCE_LIST = "image.source.list"
LASER_ON = "laser"
ILLUM_ON = "illumination"
INPUT_ACTIVE = "input_active"
INPUT_SIGNAL = "input_signal"
OUTPUT_HRES = "output_hres"
OUTPUT_VRES = "output_vres"
OUTPUT_RES = "output_res"

IDENTITY = [SYSTEM_MODEL, SYSTEM_SERIAL, SYSTEM_NAME, SYSTEM_FIRMWARE]

SUBSCRIBED = [
    SYSTEM_TARGETSTATE,
    SYSTEM_STATE,
    SYSTEM_HEALTH,
    INLET_T,
    OUTLET_T,
    MAINBOARD_T,
    LASER_STATUS,
    HDMI_SIGNAL,
    OUTPUT_SIZE,
    ILLUM_STATE,
    INPUT_SOURCE,
]

# system.state values (from the projector's introspection).
STATES = [
    "boot",
    "eco",
    "standby",
    "ready",
    "conditioning",
    "on",
    "service",
    "deconditioning",
    "error",
]
# States in which the projector is off the network or can't be driven yet.
SLEEP_STATES = ("eco", "boot")
ON_STATES = ("on", "conditioning")
HEALTH_STATES = ["Normal", "Warning", "Error"]

# Kept across a dropped connection; live readings are cleared so sensors go
# unavailable instead of showing stale values.
PERSIST_KEYS = (*IDENTITY, SOURCE_LIST)

# Methods that wake an asleep projector (wake-on-LAN) and are sent once it's up.
WAKE_METHODS = ("system.poweron", "system.gotoready")

# Parameterless commands are sent with "[]" as params, which the projector
# has always accepted from this integration.
NO_PARAMS = "[]"

_MAC_RE = re.compile(r"[0-9a-f]{12}")


class BarcoError(Exception):
    """Base error."""


class BarcoConnectionError(BarcoError, ConnectionError):
    """The projector could not be reached or dropped the connection."""


class BarcoRpcError(BarcoConnectionError):
    """The projector answered a request with a JSON-RPC error."""


class BarcoAsleep(BarcoConnectionError):
    """The projector is in eco mode (or still booting) and can't be driven."""


class BarcoAuthError(BarcoError):
    """The projector rejected the PIN code."""


def normalize_mac(mac: str) -> str:
    """``00.0d.0a.51.1b.08``, ``00:0D:0A:51:1B:08``, ``000d.0a51.1b08`` -> ``000d0a511b08``."""
    text = (mac or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F.:\- ]+", text):
        raise ValueError(f"Not a MAC address: {mac!r}")
    flat = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    if not _MAC_RE.fullmatch(flat):
        raise ValueError(f"Not a MAC address: {mac!r}")
    return flat


def _c(value: Any) -> float | None:
    return round(float(value), 1) if isinstance(value, (int, float)) else None


class BarcoDevice:
    """One projector over a single long-lived JSON-RPC session."""

    def __init__(self, host: str, mac: str, pin_code: str | None) -> None:
        """Set up the client; nothing connects until :meth:`check_connection`."""
        self.host = host
        self.mac = normalize_mac(mac)
        self._pin_code = pin_code
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._online = False
        self._authenticated = False
        # A wake method (WAKE_METHODS) to send once a woken projector is reachable.
        self._pending: str | None = None
        self._pending_until = 0.0
        self._callback: Callable[[dict[str, Any]], None] | None = None
        self._listener: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None
        self._reconnector: asyncio.Task | None = None
        self._closing = False
        self._conn_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._request_id = 1
        self._requests: dict[int, dict] = {}
        self._data: dict[str, Any] = {}
        self._sleeping = False
        self._wake_until = 0.0
        self._last_rx = 0.0
        self._buffer = ""
        self._stream_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._json_decoder = json.JSONDecoder()

    # ─── state ──

    @property
    def online(self) -> bool:
        """Whether a session is up."""
        return self._online

    @property
    def sleeping(self) -> bool:
        """Whether the projector is known to be in eco mode."""
        return self._sleeping

    @property
    def authenticated(self) -> bool:
        """Whether the PIN was accepted on this session."""
        return self._authenticated

    @property
    def data(self) -> dict[str, Any]:
        """A copy of the latest values."""
        return dict(self._data)

    @property
    def is_on(self) -> bool:
        """Whether the projector is on (or warming up to it)."""
        return (
            self._data.get(SYSTEM_TARGETSTATE) in ON_STATES
            or self._data.get(SYSTEM_STATE) in ON_STATES
        )

    def set_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Receive every change (a copy of the data)."""
        self._callback = callback

    def _notify(self) -> None:
        if self._callback is not None:
            try:
                self._callback(self.data)
            except Exception:
                _LOGGER.exception("Error in update callback")

    # ─── connection ──

    def _is_connected(self) -> bool:
        return self._online and self._writer is not None and not self._writer.is_closing()

    async def check_connection(self) -> None:
        """Connect and set up the session unless one is already up."""
        if self._is_connected():
            return
        if self._closing:
            raise BarcoConnectionError("Client closed")
        async with self._conn_lock:
            if self._is_connected():
                return
            if self._online:
                self._connection_lost(reconnect=False)
            await self._connect()

    async def async_test_connection(self) -> dict[str, Any]:
        """Connect, check the PIN, read the identity and disconnect (config flow)."""
        async with self._conn_lock:
            try:
                await self._open()
                result = await self._handshake()
            finally:
                await self._disconnect()
        return result

    async def _open(self) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, const.BARCO_PORT),
                timeout=const.BARCO_CONNECT_TIMEOUT,
            )
        except (OSError, TimeoutError) as err:
            raise BarcoConnectionError(f"Cannot connect to {self.host}: {err!r}") from err
        self._set_socket_options(writer)
        self._reader, self._writer = reader, writer
        self._buffer = ""
        self._stream_decoder.reset()
        self._requests.clear()
        self._request_id = 1
        self._authenticated = False
        self._last_rx = time.monotonic()

    async def _handshake(self) -> dict[str, Any]:
        """Read identity and state, then authenticate. Raises BarcoAsleep/BarcoAuthError."""
        result = await self._request("property.get", {"property": [*IDENTITY, SYSTEM_STATE]})
        result = result if isinstance(result, dict) else {}
        state = result.get(SYSTEM_STATE)
        if state in SLEEP_STATES or state is None:
            self._sleeping = True
            raise BarcoAsleep(f"{self.host} is not ready (state={state})")
        self._sleeping = False
        for prop in IDENTITY:
            if prop in result:
                self._data[prop] = result[prop]
        self._data[SYSTEM_STATE] = state

        if self._pin_code not in (None, ""):
            try:
                code = int(self._pin_code)
            except ValueError as err:
                raise BarcoAuthError("The PIN code must be numeric") from err
            try:
                await self._request("authenticate", {"code": code})
            except BarcoRpcError as err:
                raise BarcoAuthError(f"{self.host} rejected the PIN code") from err
            self._authenticated = True
        return result

    async def _connect(self) -> None:
        """Open and set up a session. Caller holds _conn_lock."""
        try:
            await self._open()
            if self._closing:
                raise BarcoConnectionError("Client closed")
            try:
                await self._handshake()
            except BarcoAuthError as err:
                # Reads keep working without the PIN; only control is refused.
                _LOGGER.error(
                    "%s: %s. Commands will be refused until the PIN is corrected",
                    self.host,
                    err,
                )
            await self._request("property.subscribe", {"property": SUBSCRIBED})
            self._online = True
            self._listener = asyncio.create_task(self._listen())
            self._keepalive = asyncio.create_task(self._keepalive_loop())
            # Replies arrive through the listener.
            await self.send_request("property.get", {"property": SUBSCRIBED})
            await self.send_request("image.source.list", NO_PARAMS)
            if self._pending is not None:
                method, self._pending = self._pending, None
                if time.monotonic() < self._pending_until:
                    _LOGGER.info("%s is awake; sending %s", self.host, method)
                    await self.send_request(method, NO_PARAMS)
                else:
                    _LOGGER.info("%s woke too late; not sending %s", self.host, method)
        except BaseException:
            if self._online:
                self._connection_lost(reconnect=False)
            else:
                await self._disconnect()
            raise

    @staticmethod
    def _set_socket_options(writer: asyncio.StreamWriter) -> None:
        """Ask the kernel to notice a link that has gone away."""
        sock = writer.get_extra_info("socket")
        if sock is None:
            return
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for name, value in (
                ("TCP_KEEPIDLE", 30),
                ("TCP_KEEPALIVE", 30),
                ("TCP_KEEPINTVL", 10),
                ("TCP_KEEPCNT", 3),
            ):
                opt = getattr(socket, name, None)
                if opt is not None:
                    sock.setsockopt(socket.IPPROTO_TCP, opt, value)
        except OSError as err:
            _LOGGER.debug("Could not set socket options: %s", err)

    async def _disconnect(self) -> None:
        """Close the socket without scheduling a reconnect."""
        writer, self._writer, self._reader = self._writer, None, None
        self._online = False
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(2):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass

    def _connection_lost(self, reconnect: bool = True) -> None:
        """Tear down a dead session; synchronous, as it runs from the listener's finally."""
        was_online = self._online
        self._online = False
        self._authenticated = False
        writer, self._writer, self._reader = self._writer, None, None
        self._requests.clear()
        self._buffer = ""
        if writer is not None:
            writer.close()
        current = asyncio.current_task()
        if self._keepalive is not None and self._keepalive is not current:
            self._keepalive.cancel()
        self._keepalive = None

        keep = {k: v for k, v in self._data.items() if k in PERSIST_KEYS}
        self._data = keep
        if was_online:
            self._notify()
        if reconnect:
            self._start_reconnect()

    def _start_reconnect(self) -> None:
        if self._closing or (self._sleeping and time.monotonic() >= self._wake_until):
            return
        if self._reconnector is None or self._reconnector.done():
            self._reconnector = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Reconnect in the background; after a wake-up, keep trying through the boot."""
        delay = const.BARCO_RECONNECT_DELAY
        while not self._closing and not self._online:
            waking = time.monotonic() < self._wake_until
            if self._sleeping and not waking:
                break
            await asyncio.sleep(const.BARCO_RECONNECT_DELAY if waking else delay)
            try:
                await self.check_connection()
            except (BarcoConnectionError, TimeoutError, OSError) as err:
                _LOGGER.debug("Reconnect to %s failed: %s", self.host, err)
            else:
                _LOGGER.info("Connected to %s", self.host)
                return
            delay = min(delay * 2, const.BARCO_RECONNECT_DELAY_MAX)
        if not self._online and time.monotonic() >= self._pending_until:
            self._pending = None

    async def _keepalive_loop(self) -> None:
        """Probe the link so a silently dead socket doesn't go unnoticed."""
        while True:
            await asyncio.sleep(const.BARCO_KEEPALIVE_INTERVAL)
            if not self._online:
                return
            if time.monotonic() - self._last_rx < const.BARCO_KEEPALIVE_INTERVAL:
                continue
            mark = self._last_rx
            try:
                await self.send_request("property.get", {"property": [SYSTEM_STATE]})
            except BarcoConnectionError as err:
                _LOGGER.warning("Keepalive to %s failed: %s", self.host, err)
                self._force_disconnect()
                return
            await asyncio.sleep(const.BARCO_KEEPALIVE_TIMEOUT)
            if self._online and self._last_rx == mark:
                _LOGGER.warning("No reply from %s; dropping the connection", self.host)
                self._force_disconnect()
                return

    def _force_disconnect(self) -> None:
        """Abort the transport so the listener unblocks and cleans up."""
        writer = self._writer
        if writer is None:
            self._connection_lost()
            return
        transport = writer.transport
        if transport is not None:
            transport.abort()
        else:
            writer.close()

    async def async_close(self) -> None:
        """Shut down for good (entry unload)."""
        self._closing = True
        for task in (self._reconnector, self._keepalive, self._listener):
            if task is not None:
                task.cancel()
        self._reconnector = self._keepalive = self._listener = None
        await self._disconnect()

    # ─── sending ──

    async def send_request(self, method: str, params: Any) -> int:
        """Send a request; its reply is handled by the listener. Returns its id."""
        req_id = self._request_id
        self._request_id += 1
        req = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
        self._requests[req_id] = req
        while len(self._requests) > const.BARCO_MAX_PENDING:
            del self._requests[next(iter(self._requests))]
        writer = self._writer
        if writer is None or writer.is_closing():
            raise BarcoConnectionError("Not connected")
        text = json.dumps(req)
        async with self._write_lock:
            _LOGGER.debug("%s -> %s", self.host, text)
            try:
                writer.write(text.encode())
                await asyncio.wait_for(writer.drain(), timeout=const.BARCO_WRITE_TIMEOUT)
            except (TimeoutError, OSError) as err:
                self._force_disconnect()
                raise BarcoConnectionError(f"Write to {self.host} failed: {err!r}") from err
        return req_id

    async def _request(self, method: str, params: Any) -> Any:
        """Send and wait for the reply; only used before the listener starts."""
        req_id = await self.send_request(method, params)
        deadline = time.monotonic() + const.BARCO_LOGIN_TIMEOUT
        assert self._reader is not None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BarcoConnectionError(f"No reply to {method} from {self.host}")
            try:
                chunk = await asyncio.wait_for(self._reader.read(65536), timeout=remaining)
            except TimeoutError:
                continue
            except OSError as err:
                raise BarcoConnectionError(f"{self.host}: {err!r}") from err
            if not chunk:
                raise BarcoConnectionError(f"{self.host} closed the connection")
            self._last_rx = time.monotonic()
            for msg in self._extract_messages(chunk):
                if msg.get("id") != req_id:
                    self._dispatch(msg)
                    continue
                self._requests.pop(req_id, None)
                if "error" in msg:
                    raise BarcoRpcError(f"{method} failed: {msg['error']}")
                return msg.get("result")

    # ─── receiving ──

    def _extract_messages(self, chunk: bytes) -> list[dict]:
        """Split the unframed stream into JSON messages, keeping any partial tail."""
        self._buffer += self._stream_decoder.decode(chunk)
        messages = []
        while self._buffer:
            buf = self._buffer.lstrip()
            if not buf.startswith("{"):
                start = buf.find("{")
                if start < 0:
                    self._buffer = ""
                    break
                buf = buf[start:]
            try:
                msg, end = self._json_decoder.raw_decode(buf)
            except json.JSONDecodeError:
                self._buffer = buf
                if len(self._buffer) > const.BARCO_MAX_BUFFER:
                    _LOGGER.error("Discarding %d bytes of undecodable input", len(buf))
                    self._buffer = ""
                break
            self._buffer = buf[end:]
            if isinstance(msg, dict) and msg.get("jsonrpc") == "2.0":
                messages.append(msg)
            else:
                _LOGGER.debug("Ignoring unexpected message: %s", msg)
        return messages

    async def _listen(self) -> None:
        """Handle replies and notifications until the connection ends."""
        try:
            while True:
                assert self._reader is not None
                chunk = await self._reader.read(65536)
                if not chunk:
                    _LOGGER.info("%s closed the connection", self.host)
                    break
                self._last_rx = time.monotonic()
                for msg in self._extract_messages(chunk):
                    self._dispatch(msg)
                if self._sleeping:
                    _LOGGER.info("%s is going to sleep; disconnecting", self.host)
                    break
        except asyncio.CancelledError:
            raise
        except OSError as err:
            _LOGGER.warning("Connection to %s lost: %s", self.host, err)
        except Exception:
            _LOGGER.exception("Unexpected error reading from %s", self.host)
        finally:
            self._connection_lost()

    def _dispatch(self, msg: dict) -> None:
        req_id = msg.get("id")
        if req_id is not None:
            req = self._requests.pop(req_id, None)
            if req is None:
                return
            if "error" in msg:
                _LOGGER.warning("%s rejected %s: %s", self.host, req["method"], msg["error"])
                return
            if req["method"] == "property.get":
                self._update(msg.get("result"))
            elif req["method"] == "image.source.list":
                result = msg.get("result")
                if isinstance(result, list):
                    self._data[SOURCE_LIST] = result
                    self._notify()
            return
        if "error" in msg:
            _LOGGER.warning("Error from %s: %s", self.host, msg["error"])
        elif msg.get("method") == "property.changed":
            changes: dict[str, Any] = {}
            for item in (msg.get("params") or {}).get("property") or []:
                if isinstance(item, dict):
                    changes.update(item)
            self._update(changes)

    def _update(self, values: Any) -> None:
        """Apply property values; one malformed value doesn't cost the rest."""
        if not isinstance(values, dict):
            return
        for name, value in values.items():
            try:
                self._apply(name, value)
            except Exception as err:  # noqa: BLE001 - one bad value only
                _LOGGER.warning("Bad value %s=%r from %s: %s", name, value, self.host, err)
        self._notify()

    def _apply(self, name: str, value: Any) -> None:
        if name == HDMI_SIGNAL:
            self._data[INPUT_ACTIVE] = bool(value.get("active"))
            self._data[INPUT_SIGNAL] = value.get("name") or None
        elif name == OUTPUT_SIZE:
            self._data[OUTPUT_HRES] = value["pixels"]
            self._data[OUTPUT_VRES] = value["lines"]
            self._data[OUTPUT_RES] = f"{value['pixels']}x{value['lines']}"
        elif name in (INLET_T, OUTLET_T, MAINBOARD_T):
            self._data[name] = _c(value)
        elif name == ILLUM_STATE:
            self._data[ILLUM_STATE] = value
            self._data[ILLUM_ON] = value == "On"
        elif name == LASER_STATUS:
            self._data[LASER_STATUS] = value
            self._data[LASER_ON] = value == "On"
        else:
            if name in (SYSTEM_STATE, SYSTEM_TARGETSTATE) and value != self._data.get(name):
                _LOGGER.info("%s %s: %s", self.host, name, value)
                if value == "eco":
                    self._sleeping = True
            self._data[name] = value

    # ─── commands ──

    async def _wake(self) -> None:
        _LOGGER.info("Waking %s (%s) with wake-on-LAN", self.host, self.mac)
        await asyncio.to_thread(send_magic_packet, self.mac)
        self._wake_until = time.monotonic() + const.BARCO_WAKE_WINDOW
        # A reconnect loop deep in its backoff would sleep through the boot.
        if self._reconnector is not None and not self._reconnector.done():
            self._reconnector.cancel()
        self._reconnector = None
        self._start_reconnect()

    async def _wake_command(self, method: str) -> None:
        """Send a wake method, waking the projector first if it's asleep or unreachable.

        The packet goes out straight away (harmless if the projector is merely
        disconnected); the method is sent once it accepts a connection, if that
        happens within BARCO_PENDING_TTL.
        """
        if self._online:
            await self.send_request(method, NO_PARAMS)
            return
        self._pending = method
        self._pending_until = time.monotonic() + const.BARCO_PENDING_TTL
        await self._wake()

    async def async_turn_on(self) -> None:
        """Power on, waking the projector first if needed."""
        await self._wake_command("system.poweron")

    async def async_turn_off(self) -> None:
        """Power off (the projector goes to ready or eco, per its settings).

        Nothing to do if it's asleep or unreachable.
        """
        if not self._online:
            try:
                await self.check_connection()
            except BarcoConnectionError as err:
                _LOGGER.debug("%s is already off: %s", self.host, err)
                return
        await self.async_command("system.poweroff", NO_PARAMS)

    async def async_select_source(self, source: str) -> None:
        """Switch the main window's input."""
        await self.async_command("property.set", {"property": INPUT_SOURCE, "value": source})

    async def async_command(self, method: str, params: Any = NO_PARAMS) -> None:
        """Send any JSON-RPC method.

        Wake methods (power on, go to ready) wake an asleep projector; anything
        else raises BarcoAsleep while it's asleep.
        """
        if method in WAKE_METHODS:
            await self._wake_command(method)
            return
        try:
            await self.check_connection()
        except BarcoAsleep:
            raise
        except BarcoConnectionError as err:
            if self._sleeping:
                raise BarcoAsleep(f"{self.host} is asleep") from err
            raise
        await self.send_request(method, params)

    async def async_poll(self) -> None:
        """Periodic check: reconnect if needed (also how a wake-up is noticed)."""
        await self.check_connection()
        await self.send_request("property.get", {"property": [SYSTEM_TARGETSTATE, SYSTEM_STATE]})
