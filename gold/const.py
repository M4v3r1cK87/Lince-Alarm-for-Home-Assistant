"""Costanti specifiche per Lince Gold."""

# Configuration keys
CONF_USER_CODE = "user_code"  # Codice utente per ottenere nomi zone

# API endpoints
API_GOLD_LOGIN_URL = "https://goldcloud.lince.net/api/centrale/login"
API_GOLD_SEND_COMM_URL = "https://goldcloud.lince.net/api/centrale/send_comm"

# Zone limits - SPECIFICI PER GOLD
MAX_FILARI = 7
MAX_RADIO = 64
DEFAULT_FILARI = 0
DEFAULT_RADIO = 0

# Programs - SPECIFICI PER GOLD (no GEXT)
SUPPORTS_GEXT = False
PROGRAMS = ["g1", "g2", "g3"]

# Bitmask programmi - SPECIFICI PER GOLD
MASK_G1 = 1
MASK_G2 = 2
MASK_G3 = 4

PROGRAM_BITS = {
    "g1": MASK_G1,
    "g2": MASK_G2,
    "g3": MASK_G3,
}

# Socket messages - DA VERIFICARE SE DIVERSI PER GOLD
SOCKET_MESSAGE_TYPE_PIN = 251  # Potrebbe essere diverso
SOCKET_MESSAGE_TYPE_PROGRAMS = 240  # Potrebbe essere diverso
SOCKET_NAMESPACE = "/socket"  # Potrebbe essere diverso per Gold

# Default mode mapping for Gold
DEFAULT_MODE_MAP = {
    "home": ["g1"],
    "away": ["g1", "g2", "g3"],
    "night": ["g2"],
    "vacation": ["g3"],
}