"""Binary sensors specifici per EuroPlus/EuroNET modalità locale."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from ..const import DOMAIN, MANUFACTURER
from .entity_mapping import (
    BINARY_SENSOR_CENTRALE_MAPPING,
    ZONE_FILARE_CONFIG,
    ZONE_RADIO_CONFIG,
    ZONE_ATTRIBUTES,
)

_LOGGER = logging.getLogger(__name__)


# ============================================================================
# DEVICE CLASS MAPPING
# ============================================================================

BINARY_SENSOR_DEVICE_CLASS_MAP = {
    "power": BinarySensorDeviceClass.POWER,
    "battery": BinarySensorDeviceClass.BATTERY,
    "safety": BinarySensorDeviceClass.SAFETY,
    "problem": BinarySensorDeviceClass.PROBLEM,
    "tamper": BinarySensorDeviceClass.TAMPER,
    "lock": BinarySensorDeviceClass.LOCK,
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "opening": BinarySensorDeviceClass.OPENING,
    "motion": BinarySensorDeviceClass.MOTION,
    "smoke": BinarySensorDeviceClass.SMOKE,
    "gas": BinarySensorDeviceClass.GAS,
}


# ============================================================================
# SETUP FUNCTION
# ============================================================================

def setup_euronet_binary_sensors(coordinator, config_entry: ConfigEntry, hass):
    """
    Setup COMPLETO dei binary sensors per EuroNET.
    Crea dinamicamente i sensori basandosi su BINARY_SENSOR_CENTRALE_MAPPING
    e il numero di zone configurate nella centrale.
    
    Le zone vengono create basandosi su num_zone_filari e num_zone_radio
    del coordinator, NON sui dati (che potrebbero non essere disponibili
    se il primo refresh fallisce).
    """
    entities = []
    
    # 1. Binary sensors della centrale (da mapping)
    for data_key, mapping in BINARY_SENSOR_CENTRALE_MAPPING.items():
        entity = EuroNetBinarySensor(
            coordinator=coordinator,
            config_entry=config_entry,
            data_key=data_key,
            mapping=mapping,
        )
        entities.append(entity)
        _LOGGER.debug(f"Creato binary sensor centrale: {data_key}")
    
    # 2. Zone filari (basate su num_zone_filari, non sui dati)
    num_filari = getattr(coordinator, 'num_zone_filari', 0)
    for zone_number in range(1, num_filari + 1):
        entity = EuroNetZoneBinarySensor(
            coordinator=coordinator,
            config_entry=config_entry,
            zone_number=zone_number,
            zone_type="filare",
            mapping=ZONE_FILARE_CONFIG,
        )
        entities.append(entity)
        _LOGGER.debug(f"Creato binary sensor zona filare {zone_number}")
    
    # 3. Zone radio (basate su num_zone_radio, non sui dati)
    num_radio = getattr(coordinator, 'num_zone_radio', 0)
    for zone_number in range(1, num_radio + 1):
        entity = EuroNetZoneBinarySensor(
            coordinator=coordinator,
            config_entry=config_entry,
            zone_number=zone_number,
            zone_type="radio",
            mapping=ZONE_RADIO_CONFIG,
        )
        entities.append(entity)
        _LOGGER.debug(f"Creato binary sensor zona radio {zone_number}")
    
    _LOGGER.info(f"Creati {len(entities)} binary sensor per EuroNET ({num_filari} zone filari, {num_radio} zone radio)")
    return entities


# ============================================================================
# BASE ENTITY
# ============================================================================

class EuroNetBaseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Classe base per binary sensor locali EuroPlus."""

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
        data_key: str,
        mapping: dict,
    ):
        """Inizializza l'entità base."""
        super().__init__(coordinator)
        
        self._config_entry = config_entry
        self._data_key = data_key
        self._mapping = mapping
        
        # Host per unique_id
        host = coordinator.client.host
        
        # Nome dall'entity_mapping
        self._attr_name = mapping.get("friendly_name", data_key.replace("_", " ").title())
        
        # Unique ID basato su host + data_key
        self._attr_unique_id = f"euronet_{host}_{data_key}"
        
        # Entity category (se specificata)
        entity_cat = mapping.get("entity_category")
        if entity_cat == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif entity_cat == "config":
            self._attr_entity_category = EntityCategory.CONFIG
        
        # Icon (può essere override dinamico)
        if "icon" in mapping:
            self._attr_icon = mapping["icon"]
        
        # Host per device_info
        self._host = host

    @property
    def device_info(self):
        """Device info dinamico per aggiornare sw_version."""
        sw_version = "N/A"
        if self.coordinator.data and len(self.coordinator.data) > 0:
            sw_version = str(self.coordinator.data[0].get("release_sw", "N/A"))
            
        return {
            "identifiers": {(DOMAIN, f"euronet_{self._host}")},
            "name": f"EuroNET ({self._host})",
            "manufacturer": MANUFACTURER,
            "model": "4124EURONET",
            "sw_version": sw_version,
        }

    def _get_system_data(self) -> dict | None:
        """Recupera i dati del sistema dal coordinator."""
        if self.coordinator.data and len(self.coordinator.data) > 0:
            return self.coordinator.data[0]
        return None


# ============================================================================
# BINARY SENSOR ENTITY
# ============================================================================

class EuroNetBinarySensor(EuroNetBaseBinarySensor):
    """Binary sensor generico per modalità locale, configurato dinamicamente."""

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
        data_key: str,
        mapping: dict,
    ):
        """Inizializza il binary sensor."""
        super().__init__(coordinator, config_entry, data_key, mapping)
        
        # Device class
        dc = mapping.get("device_class")
        if dc and dc in BINARY_SENSOR_DEVICE_CLASS_MAP:
            self._attr_device_class = BINARY_SENSOR_DEVICE_CLASS_MAP[dc]
        
        # Invert logic (per es. programmi G1/G2/G3/GEXT -> invertiti per device_class lock)
        self._invert = mapping.get("invert", False) or mapping.get("inverted", False)
        
        # Icon on/off
        self._icon_on = mapping.get("icon_on")
        self._icon_off = mapping.get("icon_off")

    @property
    def is_on(self) -> bool | None:
        """Restituisce True se il sensore è attivo."""
        system = self._get_system_data()
        if system:
            # Caso speciale: centrale_armata è True se almeno un programma è attivo
            if self._data_key == "centrale_armata":
                g1 = system.get("g1", False)
                g2 = system.get("g2", False)
                g3 = system.get("g3", False)
                gext = system.get("gext", False)
                return g1 or g2 or g3 or gext
            
            value = system.get(self._data_key)
            if value is not None:
                return not value if self._invert else value
        return None

    @property
    def icon(self) -> str | None:
        """Restituisce l'icona in base allo stato."""
        if self._icon_on and self._icon_off:
            return self._icon_on if self.is_on else self._icon_off
        return self._mapping.get("icon")


# ============================================================================
# ZONE BINARY SENSOR
# ============================================================================

class EuroNetZoneBinarySensor(EuroNetBaseBinarySensor):
    """Binary sensor per una zona (filare o radio)."""

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
        zone_number: int,
        zone_type: str,  # "filare" o "radio"
        mapping: dict,
    ):
        """Inizializza il binary sensor zona."""
        self._zone_number = zone_number
        self._zone_type = zone_type
        
        # Chiave: zona_filare_X o zona_radio_X
        data_key = f"zona_{zone_type}_{zone_number}"
        
        super().__init__(coordinator, config_entry, data_key, mapping)
        
        # IMPORTANTE: Rimuovi _attr_name per permettere alla property name di funzionare
        # La property name è dinamica e si aggiorna quando zone_configs diventa disponibile
        del self._attr_name
        
        # Device class per zone
        dc = mapping.get("device_class", "door")
        if dc in BINARY_SENSOR_DEVICE_CLASS_MAP:
            self._attr_device_class = BINARY_SENSOR_DEVICE_CLASS_MAP[dc]
        
        # Icon on/off
        self._icon_on = mapping.get("icon_on", "mdi:door-open")
        self._icon_off = mapping.get("icon_off", "mdi:door-closed")
        
        # Override device_info per raggruppare le zone in device separati
        host = coordinator.client.host
        self._zone_device_host = host
        self._zone_device_type = zone_type

    @property
    def name(self) -> str:
        """Nome dinamico che si aggiorna quando zone_configs diventa disponibile."""
        # Prova a recuperare il nome dalla configurazione zone (caricata dopo il login)
        zone_name = None
        if self.coordinator.zone_configs:
            if self._zone_type == "filare":
                zone_config = self.coordinator.zone_configs.zone_filari.get(self._zone_number)
            else:
                zone_config = self.coordinator.zone_configs.zone_radio.get(self._zone_number)
            
            if zone_config:
                zone_name = getattr(zone_config, "nome", "") or ""
        
        # Se non abbiamo il nome dalla config, usa il tipo come fallback
        if not zone_name:
            zone_name = f"{self._zone_type.title()} {self._zone_number}"
        
        return f"Zona {self._zone_number}: {zone_name}"

    @property
    def device_info(self):
        """Override device_info per raggruppare le zone in device separati."""
        zone_type_label = "Zone Filari" if self._zone_device_type == "filare" else "Zone Radio"
        return {
            "identifiers": {(DOMAIN, f"euronet_{self._zone_device_host}_{self._zone_device_type}")},
            "name": f"{zone_type_label} ({self._zone_device_host})",
            "manufacturer": MANUFACTURER,
            "model": "4124EURONET",
            # Collega alla centrale principale tramite via_device
            "via_device": (DOMAIN, f"euronet_{self._zone_device_host}"),
        }

    @property
    def is_on(self) -> bool | None:
        """Restituisce True se la zona è aperta."""
        system = self._get_system_data()
        if system:
            entries = system.get("entries", {})
            zone_key = f"zona_{self._zone_type}_{self._zone_number}"
            if zone_key in entries:
                return entries[zone_key].get("aperta", False)
        return None

    @property
    def icon(self) -> str | None:
        """Restituisce l'icona in base allo stato."""
        return self._icon_on if self.is_on else self._icon_off

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributi aggiuntivi della zona.
        
        Include sia lo stato runtime che la configurazione della zona
        (recuperata dal coordinator.zone_configs).
        """
        attrs = {}
        system = self._get_system_data()
        if system:
            entries = system.get("entries", {})
            zone_key = f"zona_{self._zone_type}_{self._zone_number}"
            if zone_key in entries:
                zone = entries[zone_key]
                
                # Attributi comuni di stato runtime
                for attr in ZONE_ATTRIBUTES:
                    if attr in zone:
                        attrs[attr] = zone[attr]
                
                # Attributi extra per zone radio
                if self._zone_type == "radio":
                    if "supervisione" in zone:
                        attrs["supervisione"] = zone["supervisione"]
                    if "batteria_scarica" in zone:
                        attrs["batteria_scarica"] = zone["batteria_scarica"]
        
        # Attributi di configurazione (da zone_configs, non dai dati runtime)
        if self.coordinator.zone_configs:
            if self._zone_type == "filare":
                zone_config = self.coordinator.zone_configs.zone_filari.get(self._zone_number)
            else:
                zone_config = self.coordinator.zone_configs.zone_radio.get(self._zone_number)
            
            if zone_config:
                if self._zone_type == "filare":
                    # Tipo contatto
                    tipo_label = getattr(zone_config, "tipo_label", None)
                    if tipo_label:
                        attrs["Tipo Contatto"] = tipo_label
                    
                    # Trigger
                    trigger_label = getattr(zone_config, "trigger_label", None)
                    if trigger_label:
                        attrs["Trigger"] = trigger_label
                    
                    # Tempi (sempre mostrati)
                    attrs["Tempo Ingresso (sec)"] = getattr(zone_config, "tempo_ingresso_totale", 0)
                    attrs["Tempo Uscita (sec)"] = getattr(zone_config, "tempo_uscita_totale", 0)
                    
                    # Logica e allarmi
                    logica_label = getattr(zone_config, "logica_label", None)
                    if logica_label:
                        attrs["Logica"] = logica_label
                    
                    num_allarmi = getattr(zone_config, "numero_allarmi_label", None)
                    if num_allarmi:
                        attrs["Numero Allarmi"] = num_allarmi
                    
                    # Programmi attivi (G1, G2, G3, GExt)
                    programmi = getattr(zone_config, "programmi", {})
                    if programmi:
                        programmi_attivi = [k for k, v in programmi.items() if v]
                        attrs["Programmi"] = ", ".join(programmi_attivi) if programmi_attivi else "Nessuno"
                    
                    # Opzioni booleane (mostra tutte)
                    attrs["H24"] = getattr(zone_config, "h24", False)
                    attrs["Ritardato"] = getattr(zone_config, "ritardato", False)
                    attrs["Silenzioso"] = getattr(zone_config, "silenzioso", False)
                    attrs["Parzializzabile"] = getattr(zone_config, "parzializzabile", False)
                    attrs["Percorso"] = getattr(zone_config, "percorso", False)
                    attrs["Ronda"] = getattr(zone_config, "ronda", False)
                    attrs["Test"] = getattr(zone_config, "test", False)
                    
                    # Uscite associate
                    attrs["Uscita A (Allarme 1)"] = getattr(zone_config, "uscita_a", False)
                    attrs["Uscita K (Allarme 2)"] = getattr(zone_config, "uscita_k", False)
                    attrs["Fuoco"] = getattr(zone_config, "fuoco", False)
                    attrs["Campanello"] = getattr(zone_config, "campanello", False)
                    attrs["Elettroserratura"] = getattr(zone_config, "elettroserratura", False)
                else:
                    # Attributi specifici zone radio
                    attrs["Supervisionato"] = getattr(zone_config, "supervisionato", False)
                    
                    associazioni = getattr(zone_config, "associazioni_filari", [])
                    attrs["Associazioni Filari"] = ", ".join(associazioni) if associazioni else "Nessuna"
        
        return attrs
