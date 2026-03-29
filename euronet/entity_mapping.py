"""
Entity mapping per EuroPlus/EuroNET modalità locale.

Definisce le entità da creare e come mapparle ai dati del coordinator.
Segue lo stesso pattern di europlus/entity_mapping.py per consistenza.
"""

# ============================================================================
# SENSORI (sensor)
# ============================================================================

SENSOR_MAPPING = {
    # Valori analogici dalla centrale
    "temperatura_c": {
        "friendly_name": "Temperatura",
        "device_class": "temperature",
        "state_class": "measurement",
        "unit_of_measurement": "°C",
        "icon": "mdi:thermometer",
        "suggested_display_precision": 1,
    },
    "tensione_batteria_v": {
        "friendly_name": "Tensione Batteria",
        "device_class": "voltage",
        "state_class": "measurement",
        "unit_of_measurement": "V",
        "icon": "mdi:current-dc",
        "suggested_display_precision": 2,
    },
    "tensione_bus_v": {
        "friendly_name": "Tensione BUS",
        "device_class": "voltage",
        "state_class": "measurement",
        "unit_of_measurement": "V",
        "icon": "mdi:current-dc",
        "suggested_display_precision": 2,
    },
    "release_sw": {
        "friendly_name": "Firmware Centrale",
        "icon": "mdi:chip",
    },
}


# ============================================================================
# BINARY SENSORS - STATO CENTRALE
# ============================================================================

BINARY_SENSOR_CENTRALE_MAPPING = {
    # Alimentazione
    "rete_220v": {
        "friendly_name": "Rete 220V",
        "device_class": "power",
        "icon_on": "mdi:power-plug",
        "icon_off": "mdi:power-plug-off",
    },
    "batteria_interna_ok": {
        "friendly_name": "Batteria Interna",
        "device_class": "battery",
        "invert": True,  # is_on=True se batteria OK (problema=False)
    },
    "batteria_esterna_ok": {
        "friendly_name": "Batteria Esterna", 
        "device_class": "battery",
        "invert": True,
    },
    
    # Allarmi
    "allarme": {
        "friendly_name": "Allarme",
        "device_class": "safety",
        "icon_on": "mdi:alarm-light",
        "icon_off": "mdi:alarm-light-outline",
    },
    "guasto": {
        "friendly_name": "Guasto",
        "device_class": "problem",
    },
    
    # Sabotaggi
    "sabotaggio_centrale": {
        "friendly_name": "Sabotaggio Centrale",
        "device_class": "tamper",
    },
    "sabotaggio_ingressi": {
        "friendly_name": "Sabotaggio Ingressi",
        "device_class": "tamper",
    },
    "sabotaggio_dispositivi_bus": {
        "friendly_name": "Sabotaggio Dispositivi BUS",
        "device_class": "tamper",
    },
    "allarme_integrita_bus": {
        "friendly_name": "Allarme Integrità BUS",
        "device_class": "tamper",
    },
    
    # Memorie sabotaggi
    "memoria_sabotaggio_centrale": {
        "friendly_name": "Memoria Sabotaggio Centrale",
        "device_class": "tamper",
        "entity_category": "diagnostic",
    },
    "memoria_sabotaggio_ingressi": {
        "friendly_name": "Memoria Sabotaggio Ingressi",
        "device_class": "tamper",
        "entity_category": "diagnostic",
    },
    "memoria_sabotaggio_dispositivi_bus": {
        "friendly_name": "Memoria Sabotaggio Dispositivi BUS",
        "device_class": "tamper",
        "entity_category": "diagnostic",
    },
    "memoria_integrita_bus": {
        "friendly_name": "Memoria Integrità BUS",
        "device_class": "tamper",
        "entity_category": "diagnostic",
    },
    
    # Programmi attivi (logica invertita per device_class lock)
    # Con inverted=True: programma attivo → is_on=False → "Locked"
    "g1": {
        "friendly_name": "Programma G1",
        "device_class": "lock",
        "inverted": True,
        "icon_on": "mdi:shield-lock-open-outline",  # Invertite perché stato invertito
        "icon_off": "mdi:shield-lock",
    },
    "g2": {
        "friendly_name": "Programma G2",
        "device_class": "lock",
        "inverted": True,
        "icon_on": "mdi:shield-lock-open-outline",
        "icon_off": "mdi:shield-lock",
    },
    "g3": {
        "friendly_name": "Programma G3",
        "device_class": "lock",
        "inverted": True,
        "icon_on": "mdi:shield-lock-open-outline",
        "icon_off": "mdi:shield-lock",
    },
    "gext": {
        "friendly_name": "Programma GEXT",
        "device_class": "lock",
        "inverted": True,
        "icon_on": "mdi:shield-lock-open-outline",
        "icon_off": "mdi:shield-lock",
    },
    
    # Stato armamento aggregato
    "centrale_armata": {
        "friendly_name": "Centrale Armata",
        "icon_on": "mdi:shield-check",
        "icon_off": "mdi:shield-off-outline",
        "computed": True,  # Indica che è un valore calcolato
    },
    
    # Stato generale
    "modo_servizio": {
        "friendly_name": "Modo Servizio",
        "icon_on": "mdi:wrench",
        "icon_off": "mdi:wrench-outline",
    },
    "ingressi_aperti": {
        "friendly_name": "Ingressi Aperti",
        "device_class": "opening",
    },
    "ingressi_esclusi": {
        "friendly_name": "Ingressi Esclusi",
        "icon": "mdi:cancel",
    },
    
    # Espansioni
    "espansione_1": {
        "friendly_name": "Espansione 1",
        "entity_category": "diagnostic",
        "icon": "mdi:expansion-card",
    },
    "espansione_2": {
        "friendly_name": "Espansione 2",
        "entity_category": "diagnostic",
        "icon": "mdi:expansion-card",
    },
    "espansione_3": {
        "friendly_name": "Espansione 3",
        "entity_category": "diagnostic",
        "icon": "mdi:expansion-card",
    },
    "espansione_4": {
        "friendly_name": "Espansione 4",
        "entity_category": "diagnostic",
        "icon": "mdi:expansion-card",
    },
    "espansione_5": {
        "friendly_name": "Espansione 5",
        "entity_category": "diagnostic",
        "icon": "mdi:expansion-card",
    },
    "espansione_radio": {
        "friendly_name": "Espansione Radio",
        "entity_category": "diagnostic",
        "icon": "mdi:radio-tower",
    },
}


# ============================================================================
# BINARY SENSORS - ZONE
# ============================================================================

# Attributi per le zone (usati negli extra_state_attributes)
ZONE_ATTRIBUTES = [
    "esclusa",
    "allarme_24h", 
    "memoria_24h",
    "memoria_allarme",
]

# Configurazione default per zone filari
ZONE_FILARE_CONFIG = {
    "device_class": "door",
    "icon_on": "mdi:door-open",
    "icon_off": "mdi:door-closed",
}

# Configurazione default per zone radio
ZONE_RADIO_CONFIG = {
    "device_class": "door",
    "icon_on": "mdi:door-open",
    "icon_off": "mdi:door-closed",
    # Attributi extra per zone radio
    "extra_attributes": [
        "supervisione",
        "batteria_scarica",
    ],
}
