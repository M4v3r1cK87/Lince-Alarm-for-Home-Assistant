"""Sensori (SensorEntity) comuni a tutti i brand."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.helpers import device_registry as dr
import logging

from ..const import DOMAIN, MANUFACTURER, MANUFACTURER_URL
from ..utils import prima_lettera_maiuscola

_LOGGER = logging.getLogger(__name__)


class CommonCentraleSensorEntity(CoordinatorEntity, SensorEntity):
    """Sensore comune per dati sistema/access_data - usato da tutti i brand."""
    
    def __init__(self, coordinator, row_id, centrale_id, centrale_name, key, value, unit=None):
        super().__init__(coordinator)
        self._centrale_id = centrale_id
        self._row_id = row_id
        self._value = value
        self._centrale_name = centrale_name
        self._key = key
        self._attr_name = prima_lettera_maiuscola(self._key)
        self._attr_unique_id = f"lince_{self._row_id}_{self._key}"
        self._attr_native_value = value
        self._attr_native_unit_of_measurement = unit
        
        # Categoria diagnostica per alcuni campi
        if key in ["version", "serial", "ip_locale", "gsm_id", "gsm_signal"]:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

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
    def native_value(self):
        return self._attr_native_value

    @property
    def should_poll(self):
        return False
    
    def _handle_coordinator_update(self) -> None:
        """Aggiorna valore dal coordinator."""
        for system in self.coordinator.data:
            if system["id"] == self._row_id:
                # Prima cerca in access_data
                if "access_data" in system and self._key in system["access_data"]:
                    self._attr_native_value = system["access_data"][self._key]
                # Poi nel sistema principale
                elif self._key in system:
                    self._attr_native_value = system[self._key]
                break
        super()._handle_coordinator_update()
        