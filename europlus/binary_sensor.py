"""Binary sensors specifici per Lince Europlus."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
import logging

from ..const import DOMAIN, MANUFACTURER_URL, MODEL_IMAGE_BASE
from ..common.binary_sensors import CommonCentraleBinarySensorEntity
from .entity_mapping import BINARYSENSOR_SYSTEM_KEYS, STATUSCENTRALE_MAPPING, ZONE_FILARE_CONFIG, ZONE_RADIO_CONFIG
from ..utils import prima_lettera_maiuscola, ensure_device_icon_exists

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
    "plug": BinarySensorDeviceClass.PLUG,
    "connectivity": BinarySensorDeviceClass.CONNECTIVITY,
}


# Variabili globali per stato programmi EUROPLUS
programma_g1 = False
programma_g2 = False
programma_g3 = False
programma_gext = False
timer_uscita_g1_g2_g3 = False
timer_uscita_gext = False
centrale_armata = False


def setup_europlus_binary_sensors(system, coordinator, api, config_entry, hass):
    """
    Setup COMPLETO dei binary sensors per Europlus.
    Questa funzione contiene TUTTA la logica specifica Europlus.
    """
    entities = []
    row_id = system["id"]
    centrale_id = system.get("id_centrale", row_id)
    centrale_name = system.get("name", "Sconosciuta")
    modello = system.get("modello", "default")
    
    # Download icona modello (comune ma gestito qui)
    icon_url = f"{MODEL_IMAGE_BASE}/{modello}.png"
    hass.async_create_task(ensure_device_icon_exists(hass, modello, icon_url))
    
    # Inizializza dizionari per Europlus
    if not hasattr(api, 'buscomm_sensors'):
        api.buscomm_sensors = {}
    if row_id not in api.buscomm_sensors:
        api.buscomm_sensors[row_id] = {}
    
    # 1. System data sensors (usa la classe comune ma con logica Europlus)
    for key in BINARYSENSOR_SYSTEM_KEYS:
        if key in system:
            sensor = EuroplusBinarySensor(
                coordinator=coordinator,
                row_id=row_id,
                centrale_id=centrale_id,
                centrale_name=centrale_name,
                key=key,
                value=system.get(key),
                api=api
            )
            entities.append(sensor)
    
    # 2. Zone Europlus (COMPLETAMENTE SPECIFICHE)
    if "zonesName" in system:
        entities.extend(_setup_europlus_zones(system, coordinator, api, row_id, centrale_id, centrale_name))
    
    # 3. BUSComms Europlus (COMPLETAMENTE SPECIFICI)
    entities.extend(_setup_europlus_buscomms(coordinator, system, api, row_id, centrale_id, centrale_name))
    
    return entities


def _setup_europlus_zones(system, coordinator, api, row_id, centrale_id, centrale_name):
    """Setup zone SPECIFICHE Europlus con i loro campi."""
    entities = []
    zonesName = system.get("zonesName", {})
    
    # Zone FILARI Europlus
    if "filare" in zonesName:
        for idx, zone in enumerate(zonesName['filare']):
            if zone:
                # Attributi SPECIFICI Europlus per zone filari
                attributes = {
                    'Tipo Zona': 'Filare',
                    'Numero Zona': idx + 1,
                    'Nome': zone.get('Nome', f'Zona {idx + 1}'),
                    'Ingresso Aperto': None,      # Specifico Europlus
                    'Ingresso Escluso': None,     # Specifico Europlus
                    'Memoria Allarme': None,      # Specifico Europlus
                    'Allarme 24h': None,          # Specifico Europlus
                    'Memoria 24h': None           # Specifico Europlus
                }
                attributes.update(zone)
                
                zone_sensor = EuroplusZoneBinarySensor(
                    coordinator=coordinator,
                    api=api,
                    row_id=row_id,
                    centrale_id=centrale_id,
                    centrale_name=centrale_name,
                    attributes=attributes,
                    device_class="motion"
                )
                entities.append(zone_sensor)
    
    # Zone RADIO Europlus
    if "radio" in zonesName:
        for idx, zone in enumerate(zonesName['radio']):
            if zone:
                # Attributi SPECIFICI Europlus per zone radio
                attributes = {
                    'Tipo Zona': 'Radio',
                    'Numero Zona': idx + 1,
                    'Nome': zone.get('Nome', f'Zona {idx + 1}'),
                    'Allarme 24h': None,         # Specifico Europlus
                    'Memoria 24h': None,         # Specifico Europlus
                    'Ingresso Allarme': None,    # Specifico Europlus
                    'Memoria Allarme': None,     # Specifico Europlus
                    'Supervisione': None,        # Specifico Europlus
                    'Batteria': None             # Specifico Europlus
                }
                attributes.update(zone)
                
                zone_sensor = EuroplusZoneBinarySensor(
                    coordinator=coordinator,
                    api=api,
                    row_id=row_id,
                    centrale_id=centrale_id,
                    centrale_name=centrale_name,
                    attributes=attributes,
                    device_class="motion"
                )
                entities.append(zone_sensor)
    
    return entities


def _setup_europlus_buscomms(coordinator, system, api, row_id, centrale_id, centrale_name):
    """Setup BUSComms SPECIFICI Europlus con ricorsione."""
    entities = []
    
    # Inizializza il dizionario se non esiste
    if not hasattr(api, 'buscomm_sensors'):
        api.buscomm_sensors = {}
    if row_id not in api.buscomm_sensors:
        api.buscomm_sensors[row_id] = {}
    
    # Sensore centrale armata (logica SPECIFICA Europlus)
    centrale_armata_unique_id = f"lincebuscomms_{row_id}_centrale_armata"
    if centrale_armata_unique_id not in api.buscomm_sensors[row_id]:
        entity = EuroplusBuscommBinarySensor(
            coordinator=coordinator,
            system=None,
            row_id=row_id,
            centrale_id=centrale_id,
            centrale_name=centrale_name,
            key="centrale_armata",
            configs={
                "entity_type": "binary_sensor",
                "friendly_name": "Centrale Armata",
                "device_class": "lock",
                "inverted": True,  # Armata=True → is_on=False → "Locked"
                "icon_on": "mdi:shield-lock-open-outline",  # Non Armata (invertito)
                "icon_off": "mdi:shield-lock",  # Armata (invertito)
            }
        )
        entities.append(entity)
        api.buscomm_sensors[row_id][centrale_armata_unique_id] = entity
    
    # Altri sensori dal mapping EUROPLUS con ricorsione
    entities.extend(
        _add_europlus_buscomm_recursive(coordinator, system, api, row_id, centrale_id, centrale_name, STATUSCENTRALE_MAPPING)
    )
    
    return entities


def _add_europlus_buscomm_recursive(coordinator, system, api, row_id, centrale_id, centrale_name, mapping):
    """Helper ricorsivo per aggiungere sensori BUSComm."""
    entities = []
    
    for key, value in mapping.items():
        if isinstance(value, dict) and "entity_type" not in value:
            # Ricorsione per sotto-dizionari
            entities.extend(
                _add_europlus_buscomm_recursive(coordinator, system, api, row_id, centrale_id, centrale_name, value)
            )
        elif isinstance(value, dict) and value.get("entity_type") == "binary_sensor":
            unique_id = f"lincebuscomms_{row_id}_{key}"
            if unique_id not in api.buscomm_sensors[row_id]:
                entity = EuroplusBuscommBinarySensor(
                    coordinator=coordinator,
                    system=system,
                    row_id=row_id,
                    centrale_id=centrale_id,
                    centrale_name=centrale_name,
                    key=key,
                    configs=value
                )
                entities.append(entity)
                api.buscomm_sensors[row_id][unique_id] = entity
    
    return entities


def get_entity_config(mapping, target_key):
    """Helper per ottenere configurazione entità dal mapping."""
    for key, value in mapping.items():
        if key == target_key and isinstance(value, dict) and "entity_type" in value:
            return value
        elif isinstance(value, dict):
            result = get_entity_config(value, target_key)
            if result:
                return result
    return None


def update_europlus_buscomm_binarysensors(api, row_id, keys, isStepRecursive=False):
    """Aggiorna sensori buscomms EUROPLUS - chiamabile dall'API."""
    global programma_g1, programma_g2, programma_g3, programma_gext
    global timer_uscita_g1_g2_g3, timer_uscita_gext
    
    if not hasattr(api, 'buscomm_sensors') or row_id not in api.buscomm_sensors:
        return
    
    if keys is None:
        # Reset tutti i sensori
        for key, value in api.buscomm_sensors[row_id].items():
            if value is not None and hasattr(value, 'update_values'):
                value.update_values(None)
    else:
        # Aggiorna i sensori con i valori forniti
        for key, value in keys.items():
            if isinstance(value, dict) and "entity_type" not in value:
                # Ricorsione
                update_europlus_buscomm_binarysensors(api, row_id, value, True)
                isStepRecursive = False
            else:
                config = get_entity_config(STATUSCENTRALE_MAPPING, key)
                if config and config.get("entity_type") == "binary_sensor":
                    unique_id = f"lincebuscomms_{row_id}_{key}"
                    entity = api.buscomm_sensors[row_id].get(unique_id)
                    if entity and hasattr(entity, 'update_values'):
                        entity.update_values(value)
                        # Traccia stato programmi
                        if key == "attivo_g1":
                            programma_g1 = value
                        elif key == "attivo_g2":
                            programma_g2 = value
                        elif key == "attivo_g3":
                            programma_g3 = value
                        elif key == "attivo_gext":
                            programma_gext = value
                        elif key == "tempo_out_g1g2g3":
                            timer_uscita_g1_g2_g3 = value
                        elif key == "tempo_out_gext":
                            timer_uscita_gext = value
        
        # Aggiorna centrale armata
        if not isStepRecursive:
            unique_id = f"lincebuscomms_{row_id}_centrale_armata"
            entity = api.buscomm_sensors[row_id].get(unique_id)
            if entity and hasattr(entity, 'update_values'):
                armata = (programma_g1 or programma_g2 or programma_g3 or programma_gext) and not (timer_uscita_g1_g2_g3 or timer_uscita_gext)
                entity.update_values(armata)


# ========== CLASSI SENSOR ==========

class EuroplusBinarySensor(CommonCentraleBinarySensorEntity):
    """Binary sensor Europlus per dati sistema (eredita da common)."""
    pass  # Usa l'implementazione comune


class EuroplusZoneBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor per zone specifico Europlus."""
    
    def __init__(self, coordinator, api, row_id, centrale_id, centrale_name, attributes, device_class="motion"):
        super().__init__(coordinator)
        self._api = api
        self._row_id = row_id
        self._centrale_id = centrale_id
        self._centrale_name = centrale_name
        self._zone_type = attributes['Tipo Zona']
        self._zone_number = attributes['Numero Zona']
        self._zone_name = attributes.get('Nome', f'Zona {attributes["Numero Zona"]}')
        self._attr_name = f"Zona {str(self._zone_number).zfill(2)}: {self._zone_name}"
        self._attr_unique_id = f"{self._row_id}_{self._zone_type.lower()}_{self._zone_number}"
        self._attr_extra_state_attributes = attributes
        self._state = attributes.get('Ingresso Aperto', None)
        
        # Ottieni configurazione zone dal mapping
        zone_config = ZONE_FILARE_CONFIG if self._zone_type == "Filare" else ZONE_RADIO_CONFIG
        
        # Device class dal mapping
        dc = zone_config.get("device_class", device_class)
        if dc and dc in BINARY_SENSOR_DEVICE_CLASS_MAP:
            self._attr_device_class = BINARY_SENSOR_DEVICE_CLASS_MAP[dc]
        else:
            self._attr_device_class = dc
        
        # Icone dinamiche dal mapping
        self._icon_on = zone_config.get("icon_on", "mdi:door-open")
        self._icon_off = zone_config.get("icon_off", "mdi:door-closed")
        
        # Registrazione nel dizionario dei sensori zone
        if not hasattr(self._api, "zone_sensors"):
            self._api.zone_sensors = {}
        if self._row_id not in self._api.zone_sensors:
            self._api.zone_sensors[self._row_id] = {'filare': {}, 'radio': {}}
        
        # Device info per zone
        zone_type_label = "Zone Filari" if self._zone_type == "Filare" else "Zone Radio"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._row_id}_{self._zone_type.lower()}")},
            name=zone_type_label,
            model=f"{centrale_name} - {self._centrale_id}",
            configuration_url=MANUFACTURER_URL,
            via_device=(DOMAIN, self._row_id),
        )
        
        # Registra nel dizionario appropriato
        if self._zone_type == "Filare":
            self._api.zone_sensors[self._row_id]['filare'][self._zone_number] = self
        else:
            self._api.zone_sensors[self._row_id]['radio'][self._zone_number] = self

    @property
    def is_on(self):
        """Stato della zona."""
        if self._zone_type == "Filare":
            return bool(self._attr_extra_state_attributes.get('Ingresso Aperto'))
        else:  # Radio
            return bool(self._attr_extra_state_attributes.get('Ingresso Allarme'))
    
    @property
    def icon(self) -> str | None:
        """Restituisce l'icona in base allo stato."""
        return self._icon_on if self.is_on else self._icon_off
    
    def safe_update(self):
        """Aggiorna lo stato dell'entità."""
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()
        else:
            _LOGGER.debug(f"Entità {self._attr_unique_id} non registrata: aggiornamento ignorato.")

    def update_attributes(self, zone_type, attributes):
        """Aggiorna attributi della zona."""
        if not attributes:
            attributes = {}
        
        # Flag per verificare se c'è stato un cambio di allarme
        alarm_changed = False
        
        if zone_type == "filare":
            # Controlla se è cambiato uno stato di allarme
            old_memoria = self._attr_extra_state_attributes.get('Memoria Allarme')
            old_24h = self._attr_extra_state_attributes.get('Allarme 24h')
            old_mem24h = self._attr_extra_state_attributes.get('Memoria 24h')
            
            self._attr_extra_state_attributes['Ingresso Aperto'] = attributes.get('Ingresso Aperto')
            self._attr_extra_state_attributes['Ingresso Escluso'] = attributes.get('Ingresso Escluso')
            self._attr_extra_state_attributes['Memoria Allarme'] = attributes.get('Memoria Allarme')
            self._attr_extra_state_attributes['Allarme 24h'] = attributes.get('Allarme 24h')
            self._attr_extra_state_attributes['Memoria 24h'] = attributes.get('Memoria 24h')
            
            # Verifica se è cambiato qualcosa negli allarmi
            if (old_memoria != attributes.get('Memoria Allarme') or
                old_24h != attributes.get('Allarme 24h') or
                old_mem24h != attributes.get('Memoria 24h')):
                alarm_changed = True
                
        else:  # radio
            # Controlla se è cambiato uno stato di allarme
            old_memoria = self._attr_extra_state_attributes.get('Memoria Allarme')
            old_24h = self._attr_extra_state_attributes.get('Allarme 24h')
            old_mem24h = self._attr_extra_state_attributes.get('Memoria 24h')
            
            self._attr_extra_state_attributes['Allarme 24h'] = attributes.get('Allarme 24h')
            self._attr_extra_state_attributes['Memoria 24h'] = attributes.get('Memoria 24h')
            self._attr_extra_state_attributes['Ingresso Allarme'] = attributes.get('Ingresso Allarme')
            self._attr_extra_state_attributes['Memoria Allarme'] = attributes.get('Memoria Allarme')
            self._attr_extra_state_attributes['Supervisione'] = attributes.get('Supervisione')
            self._attr_extra_state_attributes['Batteria'] = attributes.get('Batteria')
            
            # Verifica se è cambiato qualcosa negli allarmi
            if (old_memoria != attributes.get('Memoria Allarme') or
                old_24h != attributes.get('Allarme 24h') or
                old_mem24h != attributes.get('Memoria 24h')):
                alarm_changed = True
        
        self.safe_update()  # Aggiorna lo stato in Home Assistant
        
        # Se è cambiato uno stato di allarme, aggiorna il sensore ultima zona
        if alarm_changed and hasattr(self._api, 'last_alarm_zone_sensor'):
            if self._row_id in self._api.last_alarm_zone_sensor:
                sensor = self._api.last_alarm_zone_sensor[self._row_id]
                if sensor:
                    try:
                        sensor.check_and_update_alarm_zones()
                    except Exception as e:
                        _LOGGER.error(f"Errore aggiornamento sensore ultima zona allarme: {e}")


class EuroplusBuscommBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor per dati BUS specifici Europlus."""
    
    def __init__(self, coordinator, system, row_id, centrale_id, centrale_name, key, configs, value=None):
        super().__init__(coordinator)
        self._key = key
        self._row_id = row_id
        self._centrale_id = centrale_id
        self._centrale_name = centrale_name
        self._attr_unique_id = f"lincebuscomms_{self._row_id}_{self._key}"
        self._value = None
        self._state = None
        self._configs = configs
        
        # Device class
        dc = configs.get("device_class")
        if dc and dc in BINARY_SENSOR_DEVICE_CLASS_MAP:
            self._attr_device_class = BINARY_SENSOR_DEVICE_CLASS_MAP[dc]
        else:
            self._attr_device_class = None
        
        # Invert logic (per es. programmi G1/G2/G3/GEXT e batterie)
        self._invert = configs.get("inverted", False)
        
        # Icon statica o dinamica
        self._icon_static = configs.get("icon")
        self._icon_on = configs.get("icon_on")
        self._icon_off = configs.get("icon_off")
        
        # Entity category (se specificata)
        entity_cat = configs.get("entity_category")
        if entity_cat == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif entity_cat == "config":
            self._attr_entity_category = EntityCategory.CONFIG
        
        # Nome del sensore con customizzazione per programmi
        sensorName = configs.get("friendly_name", self._key)
        if system:
            accessKey = system.get("access_data", {})
            if self._key == "attivo_g1" and accessKey.get("g1"):
                sensorName = f"G1: {accessKey.get('g1')}"
            elif self._key == "attivo_g2" and accessKey.get("g2"):
                sensorName = f"G2: {accessKey.get('g2')}"
            elif self._key == "attivo_g3" and accessKey.get("g3"):
                sensorName = f"G3: {accessKey.get('g3')}"
            elif self._key == "attivo_gext" and accessKey.get("gext"):
                sensorName = f"GEXT: {accessKey.get('gext')}"
        
        self._attr_name = sensorName
        self._friendly_name = sensorName
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._row_id}_buscomms")},
            name="Comunicazioni Bus",
            model=f"{centrale_name} - {self._centrale_id}",
            configuration_url=MANUFACTURER_URL,
            via_device=(DOMAIN, self._row_id),
        )

    @property
    def should_poll(self):
        return False
    
    @property
    def is_on(self):
        if self._value is None:
            return None
        return bool(self._value)
    
    @property
    def icon(self) -> str | None:
        """Restituisce l'icona in base allo stato."""
        if self._icon_on and self._icon_off:
            return self._icon_on if self.is_on else self._icon_off
        return self._icon_static
    
    def safe_update(self):
        """Aggiorna lo stato dell'entità."""
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()
        else:
            _LOGGER.debug(f"Entità {self._attr_unique_id} non registrata.")
    
    def update_values(self, value):
        """Aggiorna il valore del sensore."""
        _LOGGER.debug(f"Aggiornamento BUSComms {self._attr_name}: {value}")
        
        # Inversione per sensori con logica invertita
        if self._invert and value is not None:
            self._value = not value
        else:
            self._value = value
        
        self.safe_update()
        