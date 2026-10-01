"""Constants for the Barco integration."""

DOMAIN = "Barco"
MANUFACTURER = "Barco"
EVENT = "barco_pulse_event"

CONF_PIN_CODE = "pin_code"

BARCO_CONNECT_TIMEOUT = 10
BARCO_LOGIN_TIMEOUT = 10
BARCO_PORT = 9090

# Reconnect / liveness handling.
BARCO_RECONNECT_DELAY = 5  # first retry after a dropped connection (s)
BARCO_RECONNECT_DELAY_MAX = 300  # backoff ceiling (s)
BARCO_KEEPALIVE_INTERVAL = 60  # probe an idle link this often (s)
BARCO_KEEPALIVE_TIMEOUT = 10  # a probe must be answered within this (s)
BARCO_WRITE_TIMEOUT = 10  # drain() must complete within this (s)
BARCO_MAX_PENDING = 64  # unanswered requests kept before dropping the oldest
BARCO_MAX_BUFFER = 1048576  # undecodable input tolerated before resyncing (bytes)
