"""Stewart Barco Device."""

import asyncio
import codecs
import json
import logging
import socket
import time

from wakeonlan import send_magic_packet

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    MANUFACTURER,
    BARCO_CONNECT_TIMEOUT,
    BARCO_KEEPALIVE_INTERVAL,
    BARCO_KEEPALIVE_TIMEOUT,
    BARCO_LOGIN_TIMEOUT,
    BARCO_MAX_BUFFER,
    BARCO_MAX_PENDING,
    BARCO_PORT,
    BARCO_RECONNECT_DELAY,
    BARCO_RECONNECT_DELAY_MAX,
    BARCO_WRITE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_SYSTEM_TARGETSTATE = "system.targetstate"
DEVICE_SYSTEM_STATE = "system.state"
DEVICE_INLET_T = "environment.temperature.inlet.value"
DEVICE_OUTLET_T = "environment.temperature.outlet.value"
DEVICE_LASER_STATUS = "illumination.sources.laser.status"
DEVICE_LASER_ON = "laser"
DEVICE_HDMI_SIGNAL = "image.connector.hdmi.detectedsignal"
DEVICE_OUTPUT_SIZE = "image.resolution.processing.size"
DEVICE_INPUT_ACTIVE = "input_active"
DEVICE_INPUT_SIGNAL = "input_signal"
DEVICE_OUTPUT_HRES = "output_hres"
DEVICE_OUTPUT_VRES = "output_vres"
DEVICE_OUTPUT_RES = "output_res"
DEVICE_MAINBOARD_T = "environment.temperature.mainboard.value"
DEVICE_ILLUM_STATE = "illumination.state"
DEVICE_ILLUM_ON = "illumination"
DEVICE_MODEL = "system.modelname"
DEVICE_SERIAL_NUM = "system.serialnumber"
DEVICE_INPUT_SOURCE = "image.window.main.source"
DEVICE_INPUT_SOURCE_LIST = "image.source.list"

PROPERTY_SUBS = [
    DEVICE_SYSTEM_TARGETSTATE,
    DEVICE_SYSTEM_STATE,
    DEVICE_INLET_T,
    DEVICE_OUTLET_T,
    DEVICE_MAINBOARD_T,
    DEVICE_LASER_STATUS,
    DEVICE_HDMI_SIGNAL,
    DEVICE_OUTPUT_SIZE,
    DEVICE_ILLUM_STATE,
    DEVICE_INPUT_SOURCE,
]

PROPERTY_INIT = PROPERTY_SUBS

# States in which the projector accepts control.
READY_STATES = ("ready", "on", "conditioning")

# Commands that are allowed to run while the projector is asleep: they are
# the ones whose whole purpose is to wake it up.
POWER_METHODS = ("system.poweron", "system.gotoready")

# Values worth keeping across a dropped connection.  Everything else is
# cleared so the sensors go unavailable instead of showing stale readings.
PERSIST_KEYS = (DEVICE_MODEL, DEVICE_SERIAL_NUM, DEVICE_INPUT_SOURCE_LIST)


class BarcoDevice:
    """Represents a single Barco device."""

    def __init__(self, hass: HomeAssistant, host: str, mac: str, pin_code: str) -> None:
        """Set up class."""

        _LOGGER.info("Initialize Barco Pulse device (host=%s, mac=%s)", host, mac)
        self._hass = hass
        self._host = host
        mac = mac.lower()
        self._mac = mac
        if len(mac) == 17:
            sep = mac[2]
            self._mac8 = mac.replace(sep, '')
        elif len(mac) == 14:
            sep = mac[4]
            self._mac8 = mac.replace(sep, '')
        else:
            raise ValueError('Incorrect MAC address format')
        self._device_id = f"{MANUFACTURER}:{self._mac8}"
        self._pin_code = pin_code
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._online = False
        self._authenticated = False
        self._poweron_pending = False
        self._callback = None
        self._listener = None
        self._keepalive = None
        self._reconnector = None
        self._closing = False
        self._conn_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._request_id = 1
        self._requests = {}
        self._data = {}
        self._sleeping = False
        self._connection_tested = False
        self._last_rx = 0.0
        self._buffer = ""
        self._stream_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._json_decoder = json.JSONDecoder()

    @property
    def device_id(self) -> str:
        """Unique device identifier."""
        return self._device_id

    @property
    def online(self) -> bool:
        """Return status."""
        return self._online

    @property
    def sleeping(self) -> bool:
        """Return True when the projector is known to be asleep."""
        return self._sleeping

    @property
    def connection_tested(self) -> bool:
        """Return connection success."""
        return self._connection_tested

    @property
    def data(self) -> dict:
        """Return data."""
        return self._data

    @property
    def sensors(self) -> list[str]:
        """Return the sensor names."""
        return PROPERTY_SUBS

    def get_sensor_value(self, name: str):
        """Return the sensor."""
        return self._data.get(name)

    def _wake_on_lan(self) -> None:
        """Wake the device via wake on lan."""
        send_magic_packet(self._mac)

    async def wakeup(self) -> None:
        """Wake up the device."""
        _LOGGER.info("Attempting to wake projector at %s", self._mac)
        await self._hass.async_add_executor_job(self._wake_on_lan)

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def _is_connected(self) -> bool:
        """Do we have a usable socket?"""
        return (
            self._online
            and self._writer is not None
            and not self._writer.is_closing()
        )

    async def check_connection(self, test: bool = False) -> None:
        """Establish a connection, unless a usable one is already up."""
        if self._is_connected():
            return

        async with self._conn_lock:
            # Another task may have connected while we waited for the lock.
            if self._is_connected():
                return
            if self._online:
                _LOGGER.debug("Closing stale connection in check_connection")
                self._connection_lost(reconnect=False)
            await self._connect(test)

    async def _connect(self, test: bool = False) -> None:
        """Open a socket and run the handshake.  Caller holds _conn_lock."""
        writer = None
        try:
            _LOGGER.debug("Attempting to establish new connection")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, BARCO_PORT),
                timeout=BARCO_CONNECT_TIMEOUT,
            )
            self._set_socket_options(writer)
            self._reader = reader
            self._writer = writer
            self._buffer = ""
            self._stream_decoder.reset()
            self._requests.clear()
            self._request_id = 1
            self._authenticated = False
            self._last_rx = time.monotonic()

            # 1. Identify the projector and check that it can be driven.
            result = await self._request(
                "property.get",
                {"property": [DEVICE_MODEL, DEVICE_SERIAL_NUM, DEVICE_SYSTEM_STATE]},
            )
            state = (result or {}).get(DEVICE_SYSTEM_STATE)
            if state not in READY_STATES:
                self._sleeping = True
                _LOGGER.debug("Projector not ready (state=%s)", state)
                raise ConnectionError(f"Device not initialized (state={state})")
            for prop, val in result.items():
                self._data[prop] = val

            if test:
                self._connection_tested = True
                await self._disconnect()
                return

            # 2. Authenticate.  A failure here is not fatal: reads keep
            #    working, but writes will be refused, so make it loud.
            if self._pin_code not in (None, ""):
                try:
                    await self._request(
                        "authenticate", {"code": int(self._pin_code)}
                    )
                    self._authenticated = True
                except ValueError:
                    _LOGGER.error("PIN code %r is not numeric", self._pin_code)
                except (ConnectionError, TimeoutError) as err:
                    _LOGGER.error(
                        "Authentication was refused (%s). Commands that change "
                        "the projector will fail until the PIN is corrected",
                        err,
                    )

            # 3. Subscribe, then start listening for unsolicited updates.
            await self._request("property.subscribe", {"property": PROPERTY_SUBS})

            self._online = True
            self._sleeping = False
            self._listener = asyncio.create_task(self.listener())
            self._keepalive = asyncio.create_task(self._keepalive_loop())

            # 4. Prime the cache.  Responses arrive via the listener.
            await self.send_request("property.get", {"property": PROPERTY_INIT})
            await self.send_request("image.source.list", "[]")
            if self._poweron_pending:
                await self.send_request("system.poweron", "[]")
                self._poweron_pending = False

        except Exception as err:
            _LOGGER.debug("Connection failed: %s", err)
            # Never leave a half-open socket or a half-initialized session
            # behind, whatever went wrong.
            if self._online:
                self._connection_lost(reconnect=False)
            elif writer is not None:
                self._reader = None
                self._writer = None
                await self._close_writer(writer)
            raise err

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

    @staticmethod
    async def _close_writer(writer: asyncio.StreamWriter) -> None:
        """Close a writer and wait for the transport to go away."""
        try:
            writer.close()
            await writer.wait_closed()
        except OSError as err:
            _LOGGER.debug("Error while closing connection: %s", err)

    async def _disconnect(self) -> None:
        """Close the current connection without scheduling a reconnect."""
        writer, self._writer = self._writer, None
        self._reader = None
        self._online = False
        if writer is not None:
            await self._close_writer(writer)

    def _connection_lost(self, reconnect: bool = True) -> None:
        """Tear down a dead connection and schedule a reconnect.

        Must stay synchronous: it runs from the listener's finally block,
        which may be executing because the task was cancelled.
        """
        was_online = self._online
        self._online = False
        self._authenticated = False
        writer, self._writer = self._writer, None
        self._reader = None
        self._requests.clear()
        self._buffer = ""
        if writer is not None:
            try:
                writer.close()
            except OSError as err:
                _LOGGER.debug("Error while closing connection: %s", err)

        current = asyncio.current_task()
        if self._keepalive is not None and self._keepalive is not current:
            self._keepalive.cancel()
        self._keepalive = None

        # Keep the identity and the source list, drop the live readings so
        # the sensors go unavailable rather than showing stale values.
        keep = {k: v for k, v in self._data.items() if k in PERSIST_KEYS}
        self._data.clear()
        self._data.update(keep)
        if was_online and self._callback is not None:
            self._callback(self._data)

        if not reconnect or self._closing or self._sleeping:
            return
        if self._reconnector is None or self._reconnector.done():
            self._reconnector = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Reconnect in the background, backing off between attempts."""
        delay = BARCO_RECONNECT_DELAY
        while not self._closing and not self._online and not self._sleeping:
            _LOGGER.debug("Reconnecting to %s in %ss", self._host, delay)
            await asyncio.sleep(delay)
            if self._closing or self._online or self._sleeping:
                return
            try:
                await self.check_connection()
                _LOGGER.info("Reconnected to %s", self._host)
                return
            except (ConnectionError, TimeoutError, OSError) as err:
                _LOGGER.debug("Reconnect to %s failed: %s", self._host, err)
            delay = min(delay * 2, BARCO_RECONNECT_DELAY_MAX)

    async def _keepalive_loop(self) -> None:
        """Probe the link so a silently dead socket does not go unnoticed."""
        while True:
            await asyncio.sleep(BARCO_KEEPALIVE_INTERVAL)
            if not self._online:
                return
            if time.monotonic() - self._last_rx < BARCO_KEEPALIVE_INTERVAL:
                # The projector is talking to us, no probe needed.
                continue
            mark = self._last_rx
            try:
                await self.send_request(
                    "property.get", {"property": [DEVICE_SYSTEM_STATE]}
                )
            except (ConnectionError, TimeoutError, OSError) as err:
                _LOGGER.warning("Keepalive to %s failed: %s", self._host, err)
                self._force_disconnect()
                return
            await asyncio.sleep(BARCO_KEEPALIVE_TIMEOUT)
            if self._online and self._last_rx == mark:
                _LOGGER.warning(
                    "No reply from %s within %ss, dropping connection",
                    self._host,
                    BARCO_KEEPALIVE_TIMEOUT,
                )
                self._force_disconnect()
                return

    def _force_disconnect(self) -> None:
        """Abort the transport so the listener unblocks and cleans up."""
        writer = self._writer
        if writer is None:
            self._connection_lost()
            return
        try:
            transport = writer.transport
            if transport is not None:
                transport.abort()
            else:
                writer.close()
        except OSError as err:
            _LOGGER.debug("Error while aborting connection: %s", err)

    async def async_close(self) -> None:
        """Shut down for good (config entry unload)."""
        self._closing = True
        for task in (self._reconnector, self._keepalive, self._listener):
            if task is not None:
                task.cancel()
        self._reconnector = self._keepalive = self._listener = None
        await self._disconnect()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send_request(self, method: str, params) -> int:
        """Format and send a request.  Returns its id."""
        req_id = self._request_id
        self._request_id += 1
        req = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
        self._requests[req_id] = req
        self._prune_requests()
        await self._write(req)
        return req_id

    async def _write(self, req: dict) -> None:
        """Put one request on the wire."""
        writer = self._writer
        if writer is None or writer.is_closing():
            raise ConnectionError("No connection to device")
        reqstr = json.dumps(req)
        async with self._write_lock:
            _LOGGER.debug("-> %s", reqstr)
            try:
                writer.write(reqstr.encode("ascii"))
                await asyncio.wait_for(writer.drain(), timeout=BARCO_WRITE_TIMEOUT)
            except (TimeoutError, OSError) as err:
                _LOGGER.warning("Write to %s failed: %s", self._host, err)
                self._force_disconnect()
                raise ConnectionError("Write failed") from err

    def _prune_requests(self) -> None:
        """Keep the pending map from growing without bound."""
        while len(self._requests) > BARCO_MAX_PENDING:
            req_id, req = next(iter(self._requests.items()))
            _LOGGER.debug("Discarding unanswered request %s (%s)", req_id, req["method"])
            del self._requests[req_id]

    async def _request(self, method: str, params, timeout: float | None = None):
        """Send a request and wait for its response.

        Only used during the handshake, before the listener owns the reader.
        Anything else arriving meanwhile is dispatched normally.
        """
        if timeout is None:
            timeout = BARCO_LOGIN_TIMEOUT
        req_id = await self.send_request(method, params)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"No response to {method}")
            chunk = await asyncio.wait_for(self._reader.read(4096), timeout=remaining)
            if not chunk:
                raise ConnectionError("Connection closed by device")
            self._last_rx = time.monotonic()
            for msg in self._extract_messages(chunk):
                if msg.get("id") != req_id:
                    self._dispatch(msg)
                    continue
                self._requests.pop(req_id, None)
                if "error" in msg:
                    raise ConnectionError(f"{method} failed: {msg['error']}")
                return msg.get("result")

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    def _extract_messages(self, chunk: bytes) -> list[dict]:
        """Turn a stream of bytes into whole JSON messages.

        The projector does not delimit its messages and a read can end in
        the middle of one, so anything incomplete stays in the buffer until
        the rest of it arrives.
        """
        self._buffer += self._stream_decoder.decode(chunk)
        messages = []
        while self._buffer:
            buf = self._buffer.lstrip()
            if not buf.startswith("{"):
                # Resynchronize on the start of the next message.
                start = buf.find("{")
                if start < 0:
                    self._buffer = ""
                    break
                _LOGGER.debug("Skipping %d bytes of stream noise", start)
                buf = buf[start:]
            try:
                msg, end = self._json_decoder.raw_decode(buf)
            except json.JSONDecodeError:
                # Incomplete: keep it and wait for the rest.
                self._buffer = buf
                if len(self._buffer) > BARCO_MAX_BUFFER:
                    _LOGGER.error("Discarding %d bytes of undecodable input",
                                  len(self._buffer))
                    self._buffer = ""
                break
            _LOGGER.debug("<- %s", buf[:end])
            self._buffer = buf[end:]
            if isinstance(msg, dict) and msg.get("jsonrpc") == "2.0":
                messages.append(msg)
            else:
                _LOGGER.warning("Ignoring unexpected message: %s", msg)
        return messages

    async def listener(self) -> None:
        """Listen for status updates from device."""
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    _LOGGER.warning("Connection to %s closed by device", self._host)
                    break
                self._last_rx = time.monotonic()
                for msg in self._extract_messages(chunk):
                    self._dispatch(msg)
                if self._sleeping:
                    _LOGGER.info("Projector is asleep, closing connection")
                    break
        except asyncio.CancelledError:
            raise
        except OSError as err:
            _LOGGER.warning("Connection to %s lost: %s", self._host, err)
        except Exception:  # noqa: BLE001 - never let the listener die quietly
            _LOGGER.exception("Unexpected error reading from %s", self._host)
        finally:
            self._connection_lost()

    def _dispatch(self, resp: dict) -> None:
        """Act on one decoded message."""
        req_id = resp.get("id")
        if req_id is not None:
            req = self._requests.pop(req_id, None)
            if req is None:
                _LOGGER.debug("Response to unknown request %s: %s", req_id, resp)
                return
            _LOGGER.debug("req_id=%s req=%s", req_id, req)
            if "error" in resp:
                _LOGGER.warning(
                    "Projector rejected %s: %s", req["method"], resp["error"]
                )
                return
            if req["method"] == "property.get":
                self.property_update(resp.get("result"))
            elif req["method"] == "image.source.list":
                self._data[DEVICE_INPUT_SOURCE_LIST] = resp.get("result")
                if self._callback is not None:
                    self._callback(self._data)
            return

        if "error" in resp:
            _LOGGER.warning("Error from projector: %s", resp["error"])
        elif resp.get("method") == "property.changed":
            self.property_update(resp["params"]["property"][0])

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def test_connection(self) -> None:
        """Test a connect."""
        await self.check_connection(test=True)

    async def send_command(self, method: str, params) -> None:
        """Make an API call."""
        if method in POWER_METHODS and not self._online:
            _LOGGER.warning("Projector is not online, waking up")
            await self.wakeup()
            if method == "system.poweron":
                self._poweron_pending = True
            return

        if self._sleeping and method not in POWER_METHODS:
            raise HomeAssistantError(
                "Projector is asleep; turn it on before sending "
                f"{method}"
            )

        await self.check_connection()
        await self.send_request(method, params)

    async def update_data(self) -> None:
        """Stuff that has to be polled."""
        _LOGGER.debug("Updating data")
        # This doubles as the wake-up probe, so unlike a user command it
        # does not take the "asleep" shortcut: a successful connect is how
        # we find out the projector is back.
        await self.check_connection()
        await self.send_request(
            "property.get",
            {"property": [DEVICE_SYSTEM_TARGETSTATE, DEVICE_SYSTEM_STATE]},
        )

    @property
    def is_on(self) -> bool:
        """Is Projector on."""
        return self._data.get(DEVICE_SYSTEM_TARGETSTATE) in ["on", "conditioning"]

    @property
    def source_list(self) -> list[str]:
        """Return source list."""
        return self._data.get(DEVICE_INPUT_SOURCE_LIST)

    @property
    def source(self) -> str:
        """Current source."""
        return self._data.get(DEVICE_INPUT_SOURCE)

    async def turn_on(self) -> None:
        """Turn on the power."""
        await self.send_command("system.poweron", "[]")

    async def turn_off(self) -> None:
        """Turn on the power."""
        await self.send_command("system.poweroff", "[]")

    async def select_source(self, source: str) -> None:
        """Set the input."""
        await self.send_command(
            "property.set", {"property": DEVICE_INPUT_SOURCE, "value": source}
        )

    async def async_init(self, data_callback: callback) -> None:
        """Initialize the device."""
        self._callback = data_callback

    def property_update(self, updates) -> None:
        """Update properties."""
        if updates is None:
            return
        for n, v in updates.items():
            # One malformed value must not cost us the rest of the batch.
            try:
                _LOGGER.debug("Projector update: %s=%s", n, v)
                if n == DEVICE_HDMI_SIGNAL:
                    self._data[DEVICE_INPUT_ACTIVE] = v["active"]
                    self._data[DEVICE_INPUT_SIGNAL] = v["name"]
                elif n == DEVICE_OUTPUT_SIZE:
                    pixels = self._data[DEVICE_OUTPUT_HRES] = v["pixels"]
                    lines = self._data[DEVICE_OUTPUT_VRES] = v["lines"]
                    self._data[DEVICE_OUTPUT_RES] = f"{pixels}x{lines}"
                elif n in (DEVICE_INLET_T, DEVICE_OUTLET_T, DEVICE_MAINBOARD_T):
                    self._data[n] = (v / 5 * 9) + 32
                elif n == DEVICE_ILLUM_STATE:
                    self._data[DEVICE_ILLUM_ON] = (v == "On")
                elif n == DEVICE_LASER_STATUS:
                    self._data[DEVICE_LASER_ON] = (v == "On")
                    self._data[DEVICE_LASER_STATUS] = v
                else:
                    if v != self._data.get(n):
                        if n == DEVICE_SYSTEM_STATE:
                            _LOGGER.info("Projector state: %s", v)
                        elif n == DEVICE_SYSTEM_TARGETSTATE:
                            _LOGGER.info("Projector target state: %s", v)
                        if n in (DEVICE_SYSTEM_STATE, DEVICE_SYSTEM_TARGETSTATE) and v == "eco":
                            _LOGGER.info("Projector going to sleep")
                            self._sleeping = True
                        self._data[n] = v

            except Exception as exc:  # noqa: BLE001 - one bad property only
                _LOGGER.error("Exception updating %s=%s: %s", n, v, exc)

        if self._callback is not None:
            try:
                self._callback(self._data)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Exception in update callback")
