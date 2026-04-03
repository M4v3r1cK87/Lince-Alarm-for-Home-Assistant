"""Binary sensors comuni a tutti i brand."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.helpers import device_registry as dr
import logging

from ..const import DOMAIN, MANUFACTURER, MANUFACTURER_URL
from ..utils import prima_lettera_maiuscola

_LOGGER = logging.getLogger(__name__)


class CommonCentraleBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor comune per dati sistema - usato da tutti i brand."""
    
    def __init__(self, coordinator, row_id, centrale_id, centrale_name, key, value, api=None):
        super().__init__(coordinator)
        self._centrale_id = centrale_id
        self._row_id = row_id
        self._value = value
        self._centrale_name = centrale_name
        self._key = key
        self._attr_name = prima_lettera_maiuscola(self._key)
        self._attr_unique_id = f"lince_{self._row_id}_{self._key}"
        self.api = api

    @property
    def device_info(self):
        """Device info comune."""
        system = next((s for s in self.coordinator.data if s["id"] == self._row_id), None)
        if system is None:
            return None

        centrale_name = f'Centrale Lince {self._centrale_name} - {self._centrale_id}'
        connections = {(dr.CONNECTION_NETWORK_MAC, system["mac"])} if system.get("mac") else set()
        
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._row_id))},
            name=centrale_name,
            manufacturer=MANUFACTURER,
            model=system.get("model", "Unknown").strip(),
            configuration_url=MANUFACTURER_URL,
            entry_type=DeviceEntryType.SERVICE,
            connections=connections,
        )

    @property
    def should_poll(self):
        return False
    
    @property
    def is_on(self):
        return bool(self._value)
    
    def _handle_coordinator_update(self) -> None:
        """Aggiorna valore dal coordinator."""
        for system in self.coordinator.data:
            if system["id"] == self._row_id:
                if self._key in system:
                    self._value = system[self._key]
                break
        super()._handle_coordinator_update()


class CommonSocketConnectionSensor(BinarySensorEntity):
    """Sensore connessione socket comune a tutti i brand."""
    
    def __init__(self, row_id, centrale_name, api):
        self._row_id = row_id
        self._centrale_name = centrale_name
        self._api = api
        self._attr_native_value = None
        self._attr_device_class = "connectivity"
        self._attr_name = "Socket Connected"
        self._attr_unique_id = f"lince_{self._row_id}_socket_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._row_id))}
        )
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Registrazione nel dizionario dei sensori socket
        if not hasattr(self._api, "socket_connection_sensor"):
            self._api.socket_connection_sensor = {}
        self._api.socket_connection_sensor[self._row_id] = self

    def safe_update(self):
        """Aggiorna lo stato dell'entità solo se è registrata in Home Assistant."""
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()
        else:
            _LOGGER.debug(f"Entità {self._attr_unique_id} non registrata: aggiornamento ignorato.")

    def update_status(self, is_connected: bool):
        self._attr_native_value = is_connected
        self.safe_update()

    @property
    def is_on(self):
        return self._api.is_socket_connected(self._row_id)

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC
    