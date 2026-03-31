"""Binary sensors specifici per Lince Gold."""
import logging
from ..common.binary_sensors import CommonCentraleBinarySensorEntity
from .entity_mapping import BINARYSENSOR_SYSTEM_KEYS, STATUSCENTRALE_MAPPING
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from ..const import DOMAIN, MANUFACTURER_URL

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


# Variabili globali per tracciare lo stato dei programmi
programma_g1 = False
programma_g2 = False
programma_g3 = False
programma_gext = False
timer_uscita_g1_g2_g3 = None
timer_uscita_gext = None


def setup_gold_binary_sensors(system, coordinator, api, config_entry, hass, async_add_entities=None):
    """
    Setup COMPLETO dei binary sensors per Gold.
    Include sensori sistema, buscomm e sensori radio.
    
    Args:
        async_add_entities: Callback opzionale per aggiungere entità dinamicamente.
                           Usato per sensori radio che vengono creati in modo asincrono.
    """
    entities = []
    row_id = system["id"]
    centrale_id = system.get("id_centrale", row_id)
    centrale_name = system.get("name", "Sconosciuta")
    
    # DEBUG: Log per capire gli ID
    _LOGGER.info(f"[Gold] setup_gold_binary_sensors chiamato:")
    _LOGGER.info(f"  - system['id'] (row_id): {row_id} (type: {type(row_id).__name__})")
    _LOGGER.info(f"  - system['id_centrale']: {centrale_id}")
    _LOGGER.info(f"  - config_entry.options keys: {list(config_entry.options.keys())}")
    systems_config_debug = config_entry.options.get("systems_config", {})
    _LOGGER.info(f"  - systems_config keys: {list(systems_config_debug.keys())}")

    # Inizializza dizionari per Gold
    if not hasattr(api, 'buscomm_sensors'):
        api.buscomm_sensors = {}
    if row_id not in api.buscomm_sensors:
        api.buscomm_sensors[row_id] = {}
    
    _LOGGER.info(f"Setup Gold binary sensors per sistema {row_id}")
    
    # Funzione asincrona per avvio socket e creazione sensori radio
    async def start_socket_and_create_radio_sensors():
        try:
            # Avvia connessione socket
            if hasattr(api, 'start_socket_connection'):
                if not api.is_socket_connected(row_id):
                    _LOGGER.info(f"[{row_id}] Avvio connessione socket Gold...")
                    await api.start_socket_connection(row_id)
                else:
                    _LOGGER.debug(f"[{row_id}] Socket Gold già connessa")
            
            # Prova a recuperare physical map se abbiamo user_code
            # Il user_code è salvato nelle opzioni del sistema specifico (systems_config)
            systems_config = config_entry.options.get("systems_config", {})
            
            # DEBUG: Log per verificare la struttura
            _LOGGER.debug(f"[{row_id}] config_entry.options keys: {list(config_entry.options.keys())}")
            _LOGGER.debug(f"[{row_id}] systems_config keys: {list(systems_config.keys())}")
            _LOGGER.debug(f"[{row_id}] Looking for key: '{str(row_id)}'")
            
            system_config = systems_config.get(str(row_id), {})
            _LOGGER.debug(f"[{row_id}] system_config: {system_config}")
            
            user_code = system_config.get("user_code", "")
            
            if not user_code:
                # Fallback: prova nella data principale (per codice inserito in fase di login)
                user_code = config_entry.data.get("user_code", "")
                if user_code:
                    _LOGGER.info(f"[{row_id}] user_code trovato in config_entry.data (login iniziale)")
            
            # LOG IMPORTANTE: stato user_code
            if user_code:
                _LOGGER.info(f"[{row_id}] ✓ user_code presente (lunghezza: {len(user_code)})")
            else:
                _LOGGER.warning(f"[{row_id}] ✗ user_code NON trovato - nessun sensore radio sarà creato")
            
            # LOG: stato async_add_entities
            _LOGGER.info(f"[{row_id}] async_add_entities callback: {'✓ disponibile' if async_add_entities else '✗ NON disponibile'}")
            
            if user_code and hasattr(api, 'fetch_and_cache_physical_map'):
                id_centrale_str = str(centrale_id)
                _LOGGER.info(f"[{row_id}] Chiamata fetch_and_cache_physical_map per centrale {id_centrale_str}...")
                physical_map = await api.fetch_and_cache_physical_map(id_centrale_str, user_code)
                
                if physical_map:
                    # LOG: contenuto physical_map
                    radio_count = len(physical_map.get("radio", []))
                    bus_count = len(physical_map.get("bus", []))
                    filari_count = len(physical_map.get("filari", []))
                    _LOGGER.info(f"[{row_id}] ✓ Physical map ricevuta: {radio_count} radio, {bus_count} bus, {filari_count} filari")
                    
                    # Crea sensori radio
                    radio_sensors = setup_gold_radio_sensors(
                        coordinator=coordinator,
                        row_id=row_id,
                        centrale_id=str(centrale_id),
                        centrale_name=centrale_name,
                        physical_map=physical_map,
                        api=api
                    )
                    
                    if radio_sensors:
                        _LOGGER.info(f"[{row_id}] ✓ Creati {len(radio_sensors)} sensori radio Gold")
                        
                        # Aggiungi le entità a Home Assistant tramite callback
                        if async_add_entities:
                            async_add_entities(radio_sensors)
                            _LOGGER.info(
                                f"[{row_id}] ✓ SUCCESSO: {len(radio_sensors)} sensori radio aggiunti a Home Assistant"
                            )
                        else:
                            _LOGGER.error(
                                f"[{row_id}] ✗ ERRORE CRITICO: async_add_entities non disponibile! "
                                f"I {len(radio_sensors)} sensori radio sono stati creati ma NON aggiunti a HA"
                            )
                    else:
                        _LOGGER.warning(f"[{row_id}] Nessun sensore radio creato dalla physical_map (nessun tipo supportato?)")
                else:
                    _LOGGER.error(f"[{row_id}] ✗ Physical map NON ricevuta (fetch_and_cache_physical_map ha ritornato None)")
            else:
                if not user_code:
                    _LOGGER.warning(
                        f"[{row_id}] User code non configurato. "
                        "Per vedere i sensori radio, configura il codice utente nelle opzioni."
                    )
                else:
                    _LOGGER.error(f"[{row_id}] API non ha metodo fetch_and_cache_physical_map!")
                
        except Exception as e:
            _LOGGER.error(f"[{row_id}] Errore avvio socket Gold: {e}", exc_info=True)
    
    # Schedula l'avvio della socket in modo asincrono
    hass.async_create_task(start_socket_and_create_radio_sensors())
    
    # Per ora Gold usa solo i sensori comuni dal sistema
    # (questi sono condivisi tra tutti i brand)
    for key in BINARYSENSOR_SYSTEM_KEYS:
        if key in system:
            sensor = GoldBinarySensor(
                coordinator=coordinator,
                row_id=row_id,
                centrale_id=centrale_id,
                centrale_name=centrale_name,
                key=key,
                value=system.get(key),
                api=api
            )
            entities.append(sensor)
    
    # TODO: Implementare quando avremo le specifiche Gold:
    # - Zone Gold (se esistono e come sono strutturate)
    # - BUSComms Gold (se esiste e com'è diverso da Europlus)
    # - Altri sensori specifici Gold
    
    # Sensore centrale allarmata (logica SPECIFICA Gold)
    centrale_allarmata_unique_id = f"lincebuscomms_{row_id}_centrale_allarmata"
    if centrale_allarmata_unique_id not in api.buscomm_sensors[row_id]:
        entity = GoldBuscommBinarySensor(
            coordinator=coordinator,
            system=None,
            row_id=row_id,
            centrale_id=centrale_id,
            centrale_name=centrale_name,
            key="centrale_allarmata",
            configs={
                "entity_type": "binary_sensor",
                "friendly_name": "Centrale Allarmata",
                "device_class": "lock",
                "inverted": True,  # Allarmata=True → is_on=False → "Locked"
                "icon_on": "mdi:shield-lock-open-outline",  # Non allarmata (invertito)
                "icon_off": "mdi:shield-lock",  # Allarmata (invertito)
            }
        )
        entities.append(entity)
        api.buscomm_sensors[row_id][centrale_allarmata_unique_id] = entity
    
    # Altri sensori dal mapping GOLD con ricorsione
    entities.extend(
        _add_gold_buscomm_recursive(coordinator, system, api, row_id, centrale_id, centrale_name, STATUSCENTRALE_MAPPING)
    )
    
    return entities

def _add_gold_buscomm_recursive(coordinator, system, api, row_id, centrale_id, centrale_name, mapping):
    """Helper ricorsivo per aggiungere sensori BUSComm."""
    entities = []
    
    _LOGGER.debug(f"_add_gold_buscomm_recursive: elaborando mapping con {len(mapping)} chiavi")
    
    for key, value in mapping.items():
        if isinstance(value, dict) and "entity_type" not in value:
            # Ricorsione per sotto-dizionari
            _LOGGER.debug(f"Ricorsione su sotto-dizionario: {key}")
            entities.extend(
                _add_gold_buscomm_recursive(coordinator, system, api, row_id, centrale_id, centrale_name, value)
            )
        elif isinstance(value, dict) and value.get("entity_type") == "binary_sensor":
            unique_id = f"lincebuscomms_{row_id}_{key}"
            _LOGGER.info(f"Creazione binary_sensor Gold: {unique_id} (friendly_name: {value.get('friendly_name', key)})")
            if unique_id not in api.buscomm_sensors[row_id]:
                entity = GoldBuscommBinarySensor(
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

def update_gold_buscomm_binarysensors(api, row_id, keys, isStepRecursive=False):
    """Aggiorna sensori buscomms GOLD - chiamabile dall'API."""
    global programma_g1, programma_g2, programma_g3, programma_gext
    global timer_uscita_g1_g2_g3, timer_uscita_gext

    _LOGGER.debug(f"update_gold_buscomm_binarysensors: row_id={row_id}, isStepRecursive={isStepRecursive}")
    
    if not hasattr(api, 'buscomm_sensors'):
        _LOGGER.debug(f"[{row_id}] api non ha buscomm_sensors")
        return
    if row_id not in api.buscomm_sensors:
        _LOGGER.debug(f"[{row_id}] row_id non presente in buscomm_sensors. Keys disponibili: {list(api.buscomm_sensors.keys())}")
        return
    
    _LOGGER.debug(f"[{row_id}] Entità registrate: {list(api.buscomm_sensors[row_id].keys())}")
    
    programs_changed = False  # Flag per tracciare se g1/g2/g3 sono cambiati
    
    if keys is None:
        # Reset tutti i sensori
        for key, value in api.buscomm_sensors[row_id].items():
            if value is not None and hasattr(value, 'update_values'):
                value.update_values(None)
        # Resetta anche i programmi
        programma_g1 = False
        programma_g2 = False
        programma_g3 = False
        programs_changed = True
    else:
        # Aggiorna i sensori con i valori forniti
        for key, value in keys.items():
            if isinstance(value, dict) and "entity_type" not in value:
                # Ricorsione per sotto-dizionari (es: "stato", "prog", "alim")
                _LOGGER.debug(f"[{row_id}] Ricorsione su sotto-dizionario: {key}")
                update_gold_buscomm_binarysensors(api, row_id, value, True)
                isStepRecursive = False
            else:
                config = get_entity_config(STATUSCENTRALE_MAPPING, key)
                if config and config.get("entity_type") == "binary_sensor":
                    unique_id = f"lincebuscomms_{row_id}_{key}"
                    entity = api.buscomm_sensors[row_id].get(unique_id)
                    if entity and hasattr(entity, 'update_values'):
                        entity.update_values(value)
                        _LOGGER.debug(f"[{row_id}] Update binary_sensor: {key} = {value}")
                        # Traccia stato programmi
                        if key == "g1":
                            if programma_g1 != value:
                                programs_changed = True
                            programma_g1 = value
                        elif key == "g2":
                            if programma_g2 != value:
                                programs_changed = True
                            programma_g2 = value
                        elif key == "g3":
                            if programma_g3 != value:
                                programs_changed = True
                            programma_g3 = value
                    else:
                        _LOGGER.debug(f"[{row_id}] Entità non trovata per {unique_id}")
        
        # Aggiorna centrale allarmata e pannello allarme
        if not isStepRecursive:
            # Aggiorna sensore centrale allarmata
            unique_id = f"lincebuscomms_{row_id}_centrale_allarmata"
            entity = api.buscomm_sensors[row_id].get(unique_id)
            if entity and hasattr(entity, 'update_values'):
                allarmata = programma_g1 or programma_g2 or programma_g3
                entity.update_values(allarmata)
                _LOGGER.debug(f"[{row_id}] Centrale allarmata: {allarmata}")
            
            # Aggiorna pannello allarme se i programmi sono cambiati
            if programs_changed and hasattr(api, 'alarm_panels'):
                panel = api.alarm_panels.get(row_id)
                if panel and hasattr(panel, 'update_from_programs'):
                    panel.update_from_programs(programma_g1, programma_g2, programma_g3)
                    _LOGGER.debug(
                        f"[{row_id}] Alarm panel aggiornato: G1={programma_g1}, "
                        f"G2={programma_g2}, G3={programma_g3}"
                    )


class GoldBinarySensor(CommonCentraleBinarySensorEntity):
    """Binary sensor Gold per dati sistema (eredita da common)."""
    pass  # Per ora usa l'implementazione comune


# Placeholder per future implementazioni
class GoldZoneBinarySensor:
    """
    TODO: Implementare quando avremo le specifiche delle zone Gold.
    Probabilmente saranno completamente diverse da Europlus.
    """
    pass

class GoldBuscommBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor per dati BUS specifici per centrali Gold."""
    
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
        
        # Invert logic (per es. programmi G1/G2/G3 e batterie)
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
            if self._key == "g1" and accessKey.get("g1"):
                sensorName = f"G1: {accessKey.get('g1')}"
            elif self._key == "g2" and accessKey.get("g2"):
                sensorName = f"G2: {accessKey.get('g2')}"
            elif self._key == "g3" and accessKey.get("g3"):
                sensorName = f"G3: {accessKey.get('g3')}"
        
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


# ============================================================================
# GOLD RADIO BINARY SENSOR - Sensori radio via WebSocket
# ============================================================================

# Tipi di periferiche radio (da device_stat_parser.py)
RADIO_TYPE_RADIOCOMANDO = 1
RADIO_TYPE_MOVIMENTO = 2
RADIO_TYPE_CONTATTO = 3
RADIO_TYPE_SIRENA = 4
RADIO_TYPE_USCITA = 5
RADIO_TYPE_TECNOLOGICO = 6
RADIO_TYPE_RIPETITORE = 7
RADIO_TYPE_NEBBIOGENO = 8

# Tipi che diventano binary_sensor
RADIO_TYPES_BINARY_SENSOR = {
    RADIO_TYPE_MOVIMENTO,      # PIR/Movimento
    RADIO_TYPE_CONTATTO,       # Magnetico/Tapparella
    RADIO_TYPE_SIRENA,         # Sirena - mostra guasto/tamper
    RADIO_TYPE_USCITA,         # Uscita - mostra stato (read-only fino a quando non avremo API)
    RADIO_TYPE_TECNOLOGICO,    # Allagamento/Fumo/Gas
    RADIO_TYPE_RIPETITORE,     # Ripetitore - mostra problemi
    RADIO_TYPE_NEBBIOGENO,     # Nebbiogeno - mostra "pronto"
}

# Tipi che diventano switch (gestiti in switch.py)
RADIO_TYPES_SWITCH = {
    RADIO_TYPE_USCITA,  # Uscita - controllabile
}

# Tipi che NON creano entità dirette
RADIO_TYPES_NO_ENTITY = {
    RADIO_TYPE_RADIOCOMANDO,  # Radiocomando - genera eventi, non stato
}

# Mapping tipo periferica -> device class primario
RADIO_TYPE_DEVICE_CLASS = {
    RADIO_TYPE_RADIOCOMANDO: None,
    RADIO_TYPE_MOVIMENTO: BinarySensorDeviceClass.MOTION,
    RADIO_TYPE_CONTATTO: BinarySensorDeviceClass.DOOR,
    RADIO_TYPE_SIRENA: BinarySensorDeviceClass.PROBLEM,  # Mostra guasto
    RADIO_TYPE_USCITA: BinarySensorDeviceClass.POWER,  # Mostra stato uscita (on/off)
    RADIO_TYPE_TECNOLOGICO: BinarySensorDeviceClass.SAFETY,
    RADIO_TYPE_RIPETITORE: BinarySensorDeviceClass.PROBLEM,  # Mostra problemi batteria
    RADIO_TYPE_NEBBIOGENO: BinarySensorDeviceClass.RUNNING,  # "pronto" = running
}

# Specializzazioni tipo 6 (tecnologico)
TECNOLOGICO_DEVICE_CLASS = {
    0: BinarySensorDeviceClass.MOISTURE,  # Allagamento
    1: BinarySensorDeviceClass.SMOKE,     # Fumo
    2: BinarySensorDeviceClass.GAS,       # Gas
    3: BinarySensorDeviceClass.POWER,     # Corrente
}

# Specializzazioni tipo 3 (contatto)
CONTATTO_DEVICE_CLASS = {
    0: BinarySensorDeviceClass.DOOR,       # Magnetico
    1: BinarySensorDeviceClass.VIBRATION,  # Tapparella/Tenda
}


class GoldRadioBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor per dispositivi radio Gold via WebSocket."""
    
    def __init__(
        self,
        coordinator,
        row_id: int,
        centrale_id: str,
        centrale_name: str,
        device_index: int,
        device_config: dict,
        api
    ):
        """Initialize Gold radio binary sensor."""
        super().__init__(coordinator)
        
        self._row_id = row_id
        self._centrale_id = centrale_id
        self._centrale_name = centrale_name
        self._device_index = device_index
        self._api = api
        
        # Info dispositivo dalla physical map
        self._device_config = device_config
        self._num_tipo = device_config.get("num_tipo_periferica", 0)
        self._num_spec = device_config.get("num_spec_periferica", 0)
        self._device_name = device_config.get("nome", f"Radio {device_index}")
        
        # Stato
        self._is_triggered = False
        self._raw_stat = 0
        self._parsed_stat = {}
        self._available = True
        
        # Identifiers
        self._attr_unique_id = f"lince_gold_{row_id}_radio_{device_index}"
        self._attr_name = self._device_name
        
        # Device class in base al tipo
        self._attr_device_class = self._get_device_class()
        
        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{row_id}_radio_devices")},
            name=f"{centrale_name} - Sensori Radio",
            model=f"Gold Radio",
            via_device=(DOMAIN, str(row_id)),
        )
        
        _LOGGER.debug(
            f"[{row_id}] Created Gold radio sensor: idx={device_index}, "
            f"name={self._device_name}, tipo={self._num_tipo}, spec={self._num_spec}"
        )
    
    def _get_device_class(self) -> BinarySensorDeviceClass | None:
        """Determina device class in base al tipo periferica."""
        if self._num_tipo == 3:  # Contatto
            return CONTATTO_DEVICE_CLASS.get(self._num_spec, BinarySensorDeviceClass.DOOR)
        elif self._num_tipo == 6:  # Tecnologico
            return TECNOLOGICO_DEVICE_CLASS.get(self._num_spec, BinarySensorDeviceClass.SAFETY)
        else:
            return RADIO_TYPE_DEVICE_CLASS.get(self._num_tipo)
    
    @property
    def should_poll(self) -> bool:
        return False
    
    @property
    def available(self) -> bool:
        return self._available
    
    @property
    def is_on(self) -> bool | None:
        """Ritorna True in base al tipo di sensore.
        
        - Movimento/Contatto/Tecnologico: True se triggered (allarme)
        - Sirena: True se ha problemi (guasto/tamper)
        - Uscita: True se uscita attiva
        - Ripetitore: True se ha problemi (batteria)
        - Nebbiogeno: True se "pronto" (ready to fog)
        """
        if self._num_tipo == RADIO_TYPE_SIRENA:
            # Sirena: mostra se ha problemi
            return self._parsed_stat.get("has_problem", False)
        elif self._num_tipo == RADIO_TYPE_USCITA:
            # Uscita: mostra se attiva
            return self._parsed_stat.get("stato_uscita", False)
        elif self._num_tipo == RADIO_TYPE_RIPETITORE:
            # Ripetitore: mostra se batteria scarica
            return self._parsed_stat.get("batteria_scarica", False)
        elif self._num_tipo == RADIO_TYPE_NEBBIOGENO:
            # Nebbiogeno: True se pronto a nebulizzare
            return self._parsed_stat.get("pronto", False)
        else:
            # Movimento, Contatto, Tecnologico: triggered = allarme
            return self._is_triggered
    
    @property
    def extra_state_attributes(self) -> dict:
        """Attributi extra per diagnostica e stato completo."""
        attrs = {
            "device_index": self._device_index,
            "device_type": self._num_tipo,
            "device_type_name": self._get_type_name(),
            "device_spec": self._num_spec,
            "raw_stat": self._raw_stat,
            "centrale_id": self._centrale_id,
        }
        
        # Aggiungi attributi specifici per tipo
        if self._num_tipo == RADIO_TYPE_SIRENA:
            attrs.update({
                "tamper": self._parsed_stat.get("tamper", False),
                "guasto": self._parsed_stat.get("guasto", False),
                "dormiente": self._parsed_stat.get("dormiente", False),
                "batteria_scarica": self._parsed_stat.get("batteria_scarica"),
                "supervisione_led": self._parsed_stat.get("supervisione_led", False),
            })
        elif self._num_tipo == RADIO_TYPE_NEBBIOGENO:
            attrs.update({
                "pronto": self._parsed_stat.get("pronto", False),
                "bombola_scarica": self._parsed_stat.get("bombola_scarica", False),
                "rete_assente": self._parsed_stat.get("rete_assente", False),
                "guasto": self._parsed_stat.get("guasto", False),
                "tamper": self._parsed_stat.get("tamper", False),
                "dormiente": self._parsed_stat.get("dormiente", False),
                "batteria_scarica": self._parsed_stat.get("batteria_scarica"),
            })
        elif self._num_tipo == RADIO_TYPE_RIPETITORE:
            attrs.update({
                "batteria_scarica": self._parsed_stat.get("batteria_scarica"),
            })
        elif self._num_tipo == RADIO_TYPE_USCITA:
            attrs.update({
                "stato_uscita": self._parsed_stat.get("stato_uscita", False),
                "stato_ingresso": self._parsed_stat.get("stato_ingresso", False),
                "tamper": self._parsed_stat.get("tamper", False),
                "dormiente": self._parsed_stat.get("dormiente", False),
                "batteria_scarica": self._parsed_stat.get("batteria_scarica"),
            })
        else:
            # Movimento, Contatto, Tecnologico
            attrs.update({
                "tamper": self._parsed_stat.get("tamper", False),
                "batteria_scarica": self._parsed_stat.get("batteria_scarica"),
                "memoria": self._parsed_stat.get("memoria", False),
                "dormiente": self._parsed_stat.get("dormiente", False),
            })
        
        return attrs
    
    def _get_type_name(self) -> str:
        """Nome leggibile del tipo periferica."""
        type_names = {
            RADIO_TYPE_RADIOCOMANDO: "Radiocomando",
            RADIO_TYPE_MOVIMENTO: "Movimento",
            RADIO_TYPE_CONTATTO: "Contatto",
            RADIO_TYPE_SIRENA: "Sirena",
            RADIO_TYPE_USCITA: "Uscita",
            RADIO_TYPE_TECNOLOGICO: "Tecnologico",
            RADIO_TYPE_RIPETITORE: "Ripetitore",
            RADIO_TYPE_NEBBIOGENO: "Nebbiogeno",
        }
        return type_names.get(self._num_tipo, f"Tipo {self._num_tipo}")
    
    @property
    def icon(self) -> str | None:
        """Icona in base al tipo e stato."""
        is_active = self.is_on
        
        if self._num_tipo == RADIO_TYPE_MOVIMENTO:
            return "mdi:motion-sensor" if is_active else "mdi:motion-sensor-off"
        
        elif self._num_tipo == RADIO_TYPE_CONTATTO:
            if self._num_spec == 1:  # Tapparella
                return "mdi:blinds-open" if is_active else "mdi:blinds"
            else:  # Magnetico
                return "mdi:door-open" if is_active else "mdi:door-closed"
        
        elif self._num_tipo == RADIO_TYPE_SIRENA:
            if is_active:  # Ha problemi
                return "mdi:alarm-light"
            return "mdi:alarm-light-outline"
        
        elif self._num_tipo == RADIO_TYPE_RIPETITORE:
            if is_active:  # Batteria scarica / problema
                return "mdi:access-point-network-off"
            return "mdi:access-point-network"
        
        elif self._num_tipo == RADIO_TYPE_NEBBIOGENO:
            if is_active:  # Pronto
                return "mdi:weather-fog"
            return "mdi:weather-sunny"  # Non pronto
        
        elif self._num_tipo == RADIO_TYPE_USCITA:
            # Uscita: icona con stato ON/OFF
            return "mdi:electric-switch" if is_active else "mdi:electric-switch-closed"
        
        elif self._num_tipo == RADIO_TYPE_TECNOLOGICO:
            if self._num_spec == 0:  # Allagamento
                return "mdi:water-alert" if self._is_triggered else "mdi:water-off"
            elif self._num_spec == 1:  # Fumo
                return "mdi:smoke-detector-alert" if self._is_triggered else "mdi:smoke-detector"
            elif self._num_spec == 2:  # Gas
                return "mdi:gas-cylinder" if self._is_triggered else "mdi:gas-cylinder"
        return None
    
    def update_from_websocket(self, parsed_data: dict):
        """Aggiorna lo stato dal messaggio WebSocket."""
        self._raw_stat = parsed_data.get("raw", 0)
        self._parsed_stat = parsed_data.get("stat", {})
        self._is_triggered = parsed_data.get("is_triggered", False)
        
        _LOGGER.debug(
            f"[{self._row_id}] Radio {self._device_index} update: "
            f"triggered={self._is_triggered}, raw={self._raw_stat}"
        )
        
        self.async_write_ha_state()
    
    def reset_state(self):
        """Reset stato a non triggered."""
        if self._is_triggered:
            self._is_triggered = False
            self._raw_stat = 0
            self.async_write_ha_state()


# Storage globale per sensori radio Gold
_gold_radio_sensors: dict[int, dict[int, GoldRadioBinarySensor]] = {}


def get_gold_radio_sensors(row_id: int) -> dict[int, GoldRadioBinarySensor]:
    """Ritorna i sensori radio per una centrale."""
    return _gold_radio_sensors.get(row_id, {})


async def update_gold_radio_sensors(row_id: int, dev_type: str, group: int, parsed_stats: dict):
    """
    Callback per aggiornare i sensori radio da WebSocket.
    Chiamato da GoldSocketClient.on_gold_dev_stats.
    """
    if dev_type != "radio":
        return
    
    sensors = _gold_radio_sensors.get(row_id, {})
    if not sensors:
        _LOGGER.debug(f"[{row_id}] No radio sensors registered yet")
        return
    
    for device_idx, parsed_data in parsed_stats.items():
        sensor = sensors.get(device_idx)
        if sensor:
            sensor.update_from_websocket(parsed_data)
        else:
            _LOGGER.debug(f"[{row_id}] No sensor for radio index {device_idx}")


def setup_gold_radio_sensors(
    coordinator,
    row_id: int,
    centrale_id: str,
    centrale_name: str,
    physical_map: dict,
    api
) -> list[GoldRadioBinarySensor]:
    """
    Crea i binary sensors per tutti i dispositivi radio configurati.
    
    Tipi supportati come binary_sensor:
    - Movimento (2): mostra allarme/triggered
    - Contatto (3): mostra aperto/chiuso
    - Sirena (4): mostra problemi (guasto/tamper)
    - Tecnologico (6): mostra allarme (fumo/gas/allagamento)
    - Ripetitore (7): mostra problemi (batteria)
    - Nebbiogeno (8): mostra "pronto"
    
    Args:
        coordinator: Home Assistant coordinator
        row_id: ID della centrale
        centrale_id: ID centrale (id_centrale)
        centrale_name: Nome centrale
        physical_map: Physical map con radio[], bus[], filari[]
        api: API instance
    
    Returns:
        Lista di GoldRadioBinarySensor creati
    """
    global _gold_radio_sensors
    
    entities = []
    radio_devices = physical_map.get("radio", [])
    
    # LOG: Debug della physical_map
    _LOGGER.info(f"[{row_id}] setup_gold_radio_sensors: {len(radio_devices)} dispositivi radio nella physical_map")
    
    # LOG: Mostra tutti i tipi di dispositivi presenti
    types_found = {}
    for idx, device_config in enumerate(radio_devices):
        num_tipo = device_config.get("num_tipo_periferica", 0)
        device_name = device_config.get("nome", f"Radio {idx}")
        types_found[num_tipo] = types_found.get(num_tipo, 0) + 1
        _LOGGER.debug(f"[{row_id}]   Device {idx}: tipo={num_tipo}, nome='{device_name}'")
    
    _LOGGER.info(f"[{row_id}] Tipi dispositivi trovati: {types_found}")
    _LOGGER.info(f"[{row_id}] Tipi supportati come binary_sensor: {RADIO_TYPES_BINARY_SENSOR}")
    
    if row_id not in _gold_radio_sensors:
        _gold_radio_sensors[row_id] = {}
    
    for idx, device_config in enumerate(radio_devices):
        num_tipo = device_config.get("num_tipo_periferica", 0)
        
        # Crea sensore solo per tipi che diventano binary_sensor
        if num_tipo in RADIO_TYPES_BINARY_SENSOR:
            sensor = GoldRadioBinarySensor(
                coordinator=coordinator,
                row_id=row_id,
                centrale_id=centrale_id,
                centrale_name=centrale_name,
                device_index=idx,
                device_config=device_config,
                api=api
            )
            entities.append(sensor)
            _gold_radio_sensors[row_id][idx] = sensor
            
            _LOGGER.info(
                f"[{row_id}] Created radio sensor: {device_config.get('nome', f'Radio {idx}')} "
                f"(type={num_tipo})"
            )
    
    _LOGGER.info(f"[{row_id}] Created {len(entities)} Gold radio sensors")
    return entities