"""Switch specifici per Lince Gold."""
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def setup_gold_switches(system, coordinator, api, config_entry, hass):
    """
    Setup switch SPECIFICI Gold.
    Per ora non ce ne sono, tutti gli switch sono comuni.
    
    TODO: In futuro, quando avremo l'API per comandare le uscite radio,
    creare GoldRadioSwitch per dispositivi di tipo 5 (uscita).
    Al momento sono creati come binary_sensor read-only in binary_sensor.py
    """
    entities = []
    
    # TODO: Implementare switch per uscite radio quando avremo l'API
    # I dispositivi tipo 5 (uscita) sono per ora binary_sensor read-only
    # L'API per comandarli potrebbe essere qualcosa come:
    # POST /api/centrale/set_output con body {centrale_id, device_index, stato}
    # o via WebSocket emit "setGoldOutput"
    
    return entities


# TODO: Implementare GoldRadioSwitch quando avremo l'API
class GoldRadioSwitch(SwitchEntity):
    """
    Switch per uscite radio Gold (tipo 5).
    
    Da implementare quando avremo l'API per comandare le uscite.
    Al momento, i dispositivi uscita sono binary_sensor read-only.
    """
    
    def __init__(self, coordinator, row_id: int, centrale_id: str, 
                 centrale_name: str, device_index: int, device_config: dict, api):
        """Initialize Gold radio switch."""
        super().__init__()
        self._row_id = row_id
        self._centrale_id = centrale_id
        self._centrale_name = centrale_name
        self._device_index = device_index
        self._device_config = device_config
        self._api = api
        self._is_on = False
        
        self._device_name = device_config.get("nome", f"Uscita {device_index}")
        self._attr_unique_id = f"lince_gold_{row_id}_output_{device_index}"
        self._attr_name = self._device_name
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{row_id}_radio_devices")},
            name=f"{centrale_name} - Sensori Radio",
            model="Gold Radio",
            via_device=(DOMAIN, str(row_id)),
        )
    
    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on
    
    @property
    def icon(self) -> str:
        """Return icon based on state."""
        return "mdi:electric-switch" if self._is_on else "mdi:electric-switch-closed"
    
    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        # TODO: Chiamare API Gold per attivare uscita
        # await self._api.set_gold_output(self._centrale_id, self._device_index, True)
        _LOGGER.warning(f"GoldRadioSwitch.turn_on non ancora implementato - richiede API")
    
    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        # TODO: Chiamare API Gold per disattivare uscita
        # await self._api.set_gold_output(self._centrale_id, self._device_index, False)
        _LOGGER.warning(f"GoldRadioSwitch.turn_off non ancora implementato - richiede API")
    
    def update_from_websocket(self, parsed_data: dict):
        """Update state from WebSocket."""
        self._is_on = parsed_data.get("stato_uscita", False)
        self.async_write_ha_state()
