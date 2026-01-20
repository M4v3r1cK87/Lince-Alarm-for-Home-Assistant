"""Costanti specifiche per EuroPlus/EuroNET modalità locale."""

# ============================================================================
# CONFIGURAZIONE CONNESSIONE LOCALE
# ============================================================================

# Chiavi config_entry
CONF_LOCAL_MODE = "local_mode"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_PASSWORD = "password"
CONF_INSTALLER_CODE = "installer_code"

# Username fisso per EuroNET (non modificabile)
DEFAULT_LOCAL_USERNAME = "admin"

# Porta default
DEFAULT_LOCAL_PORT = 80

# ============================================================================
# CONFIGURAZIONE ZONE
# ============================================================================

CONF_NUM_ZONE_FILARI = "num_zone_filari"
CONF_NUM_ZONE_RADIO = "num_zone_radio"

# Zone limits
MAX_FILARI = 35
MAX_RADIO = 64
DEFAULT_FILARI = 0
DEFAULT_RADIO = 0

# ============================================================================
# CONFIGURAZIONE PROFILI ARM
# ============================================================================

CONF_ARM_PROFILES = "arm_profiles"

# Programs
SUPPORTS_GEXT = True
PROGRAMS = ["g1", "g2", "g3", "gext"]

# Bitmask programmi
MASK_G1 = 1
MASK_G2 = 2
MASK_G3 = 4
MASK_GEXT = 8

PROGRAM_BITS = {
    "g1": MASK_G1,
    "g2": MASK_G2,
    "g3": MASK_G3,
    "gext": MASK_GEXT
}

# Default profili ARM per Home Assistant (vuoti - l'utente configura)
DEFAULT_ARM_PROFILES = {
    "home": [],       # In casa
    "away": [],       # Fuori casa
    "night": [],      # Notte
    "vacation": [],   # Vacanza
}

# ============================================================================
# CONFIGURAZIONE POLLING
# ============================================================================

CONF_POLLING_INTERVAL = "polling_interval"
DEFAULT_POLLING_INTERVAL_MS = 500   # 500ms default
MIN_POLLING_INTERVAL_MS = 250       # 250ms minimum
MAX_POLLING_INTERVAL_MS = 60000     # 60s maximum

# Polling interval options for selector (in ms)
POLLING_INTERVAL_OPTIONS = [
    250,    # 250ms - fastest
    500,    # 500ms - default
    750,    # 750ms
    1000,   # 1s
    2000,   # 2s
    3000,   # 3s
    5000,   # 5s - consigliato per GR868
    10000,  # 10s
    30000,  # 30s
    60000,  # 60s - slowest
]
