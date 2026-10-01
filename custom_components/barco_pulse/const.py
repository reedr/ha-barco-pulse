"""Constants for the Barco Pulse integration."""

from datetime import timedelta

DOMAIN = "barco_pulse"
# The original package registered itself under this (invalid) domain.
LEGACY_DOMAIN = "Barco"
MANUFACTURER = "Barco"

CONF_PIN_CODE = "pin_code"
CONF_LEGACY_ENTRY = "legacy_entry"

UPDATE_INTERVAL = timedelta(seconds=30)

BARCO_PORT = 9090
BARCO_CONNECT_TIMEOUT = 10
BARCO_LOGIN_TIMEOUT = 10

# Reconnect / liveness handling.
BARCO_RECONNECT_DELAY = 5  # first retry after a dropped connection (s)
BARCO_RECONNECT_DELAY_MAX = 300  # backoff ceiling (s)
BARCO_WAKE_WINDOW = 180  # after wake-on-LAN, keep retrying this long (s)
BARCO_PENDING_TTL = 300  # a power-on/go-to-ready queued by a wake expires after this (s)
BARCO_KEEPALIVE_INTERVAL = 60  # probe an idle link this often (s)
BARCO_KEEPALIVE_TIMEOUT = 10  # a probe must be answered within this (s)
BARCO_WRITE_TIMEOUT = 10  # drain() must complete within this (s)
BARCO_MAX_PENDING = 64  # unanswered requests kept before dropping the oldest
BARCO_MAX_BUFFER = 1048576  # undecodable input tolerated before resyncing (bytes)
