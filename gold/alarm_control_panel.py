"""Alarm control panel specifico per Lince Gold."""
from __future__ import annotations
import asyncio
import logging
from typing import Optional, List
from datetime import datetime

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    CodeFormat,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import DOMAIN
from ..utils import send_multiple_notifications, dismiss_persistent_notification
from .const import PROGRAM_BITS

_LOGGER = logging.getLogger(__name__)

# Timeout di "decadimento" del pending se non arriva la conferma
PENDING_DECAY_SECONDS = 10.0


def setup_gold_alarm_panels(system, coordinator, api, config_entry, hass):
    """
    Setup alarm control panel SPECIFICO Gold.
    """
    entities = []
    row_id = system["id"]
    centrale_id = system.get("id_centrale", str(row_id))
    centrale_name = system.get("name", "Sconosciuta")
    
    _LOGGER.debug(f"Setup Gold alarm control panel per sistema {row_id}")
    
    # Crea il pannello di allarme Gold
    panel = GoldAlarmControlPanel(
        coordinator=coordinator,
        api=api,
        row_id=row_id,
        centrale_id=centrale_id,
        centrale_name=centrale_name,
        config_entry=config_entry
    )
    entities.append(panel)
    
    return entities


def _to_mask(programs: Optional[List[str]]) -> int:
    """Converte lista programmi in bitmask usando PROGRAM_BITS."""
    m = 0
    for p in programs or []:
        m |= PROGRAM_BITS.get(p, 0)
    return m


def _mask_to_programs_list(mask: int) -> list[str]:
    """Converte bitmask in lista programmi usando PROGRAM_BITS."""
    return [p for p, bit in PROGRAM_BITS.items() if mask & bit]


class GoldAlarmControlPanel(CoordinatorEntity, AlarmControlPanelEntity):
    """
    Alarm panel specifico per Gold.
    
    Differenze da Europlus:
    - Usa HTTP POST invece di WebSocket per arm/disarm
    - Flusso: login con codice -> send_comm con prog mask
    - Solo 3 programmi: G1, G2, G3 (no GEXT)
    """

    _attr_code_format = CodeFormat.NUMBER

    def __init__(
        self, coordinator, api, row_id, centrale_id, centrale_name, config_entry
    ):
        super().__init__(coordinator)
        self._api = api
        self._row_id = row_id
        self._centrale_id = centrale_id  # Stringa per API Gold
        self._centrale_name = centrale_name
        self._attr_name = f"Allarme {centrale_name}"
        self._attr_unique_id = f"lince_gold_{row_id}_alarm"
        self._entry = config_entry

        self._last_error: str | None = None

        # Stato ottimistico transitorio
        self._pending_state: AlarmControlPanelState | None = None
        self._pending_expected_mask: int | None = None
        self._pending_profile: str | None = None
        self._pending_timeout_task: asyncio.Task | None = None
        
        # Tracking per notifiche
        self._last_triggered_notification: Optional[datetime] = None
        self._last_known_state: Optional[AlarmControlPanelState] = None
        self._internal_command_active: bool = False
        self._initial_sync_done: bool = False

    # ---------- Proprietà base ----------
    @property
    def name(self) -> str | None:
        return self._attr_name

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(f"{DOMAIN}", self._row_id)})

    @property
    def code_arm_required(self) -> bool:
        return True

    @property
    def supported_features(self) -> int:
        """Ritorna le feature supportate in base ai profili configurati."""
        pm = self._build_profile_masks()
        feats = 0
        if pm.get("home", 0) != 0:
            feats |= AlarmControlPanelEntityFeature.ARM_HOME
        if pm.get("away", 0) != 0:
            feats |= AlarmControlPanelEntityFeature.ARM_AWAY
        if pm.get("night", 0) != 0:
            feats |= AlarmControlPanelEntityFeature.ARM_NIGHT
        if pm.get("vacation", 0) != 0:
            feats |= AlarmControlPanelEntityFeature.ARM_VACATION
        return feats

    def _build_profile_masks(self) -> dict[str, int]:
        """Costruisce le maschere per ogni profilo dalla configurazione."""
        arm_profiles = self._entry.options.get("arm_profiles", {})
        sid_str = str(self._row_id)
        prof = arm_profiles.get(sid_str, {
            "home": [], "away": [], "night": [], "vacation": []
        })
        return {
            "home": _to_mask(prof.get("home", [])),
            "away": _to_mask(prof.get("away", [])),
            "night": _to_mask(prof.get("night", [])),
            "vacation": _to_mask(prof.get("vacation", [])),
        }

    def _mask_to_ha_state_by_profiles(self, mask: int) -> AlarmControlPanelState | None:
        """Mappa una maschera a uno stato HA in base ai profili configurati."""
        if mask == 0:
            return AlarmControlPanelState.DISARMED
        
        pm = self._build_profile_masks()
        # Cerca corrispondenza esatta
        if pm.get("home") == mask:
            return AlarmControlPanelState.ARMED_HOME
        if pm.get("away") == mask:
            return AlarmControlPanelState.ARMED_AWAY
        if pm.get("night") == mask:
            return AlarmControlPanelState.ARMED_NIGHT
        if pm.get("vacation") == mask:
            return AlarmControlPanelState.ARMED_VACATION
        
        # Nessuna corrispondenza esatta
        return AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    # ---------- Stato ----------
    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """
        Determina lo stato dell'allarme.
        
        Per Gold, lo stato viene determinato dalla socket (onGoldState).
        Se non disponibile, usa il pending state locale.
        
        TODO: Implementare parsing stato da socket Gold quando disponibile
        """
        # Per ora, usa il pending state se presente
        if self._pending_state is not None:
            return self._pending_state
        
        # TODO: Leggere stato reale dalla socket Gold
        # system = self._get_system()
        # socket_msg = system.get("socket_message") if system else None
        # ...parse stato...
        
        # Fallback: DISARMED
        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self):
        attrs = {}
        pm = self._build_profile_masks()
        attrs["profile_masks"] = pm
        attrs["panel_brand"] = "lince-gold"
        if self._pending_state is not None:
            attrs["pending_state"] = self._pending_state.name
            attrs["pending_expected_mask"] = self._pending_expected_mask
            attrs["pending_profile"] = self._pending_profile
        if getattr(self, "_last_error", None):
            attrs["last_error"] = self._last_error
        return attrs

    # ---------- Gestione errori ----------
    def _set_error(self, msg: str):
        self._last_error = msg
        _LOGGER.error("[Gold %s] %s", self._row_id, msg)

    def _clear_error(self):
        self._last_error = None

    # ---------- Pending state management ----------
    def _start_pending(
        self,
        state: AlarmControlPanelState,
        expected_mask: int,
        profile: str,
        timeout: float = PENDING_DECAY_SECONDS,
    ):
        """Avvia stato pending ottimistico."""
        self._pending_state = state
        self._pending_expected_mask = expected_mask
        self._pending_profile = profile
        
        # Cancella task precedente
        if self._pending_timeout_task and not self._pending_timeout_task.done():
            self._pending_timeout_task.cancel()
        
        # Avvia timeout per decay
        self._pending_timeout_task = asyncio.create_task(
            self._pending_decay(timeout)
        )
        
        self.async_write_ha_state()

    async def _pending_decay(self, timeout: float):
        """Timeout per rimuovere pending state se non confermato."""
        try:
            await asyncio.sleep(timeout)
            self._clear_pending(write_state=True)
        except asyncio.CancelledError:
            pass

    def _clear_pending(self, write_state: bool = False):
        """Pulisce lo stato pending."""
        self._pending_state = None
        self._pending_expected_mask = None
        self._pending_profile = None
        self._internal_command_active = False
        
        if self._pending_timeout_task and not self._pending_timeout_task.done():
            self._pending_timeout_task.cancel()
        self._pending_timeout_task = None
        
        if write_state:
            self.async_write_ha_state()

    # ---------- Notifiche ----------
    async def _send_armed_notification(self, profile: str = None):
        """Invia notifica ARMED."""
        profile_names = {
            "home": "HOME",
            "away": "AWAY",
            "night": "NIGHT",
            "vacation": "VACATION",
            "custom": "CUSTOM"
        }
        
        try:
            await send_multiple_notifications(
                self.hass,
                message=f"🔒 {self._attr_name} armata in modalità {profile_names.get(profile, profile.upper() if profile else 'ARMED')}",
                title=f"Lince Gold - {self._attr_name} - Sistema Armato",
                persistent=True,
                persistent_id=f"alarm_armed_{self._row_id}",
                mobile=True,
                centrale_id=self._row_id,
                data={
                    "tag": f"alarm_armed_{self._row_id}",
                    "priority": "high",
                    "color": "green",
                    "notification_icon": "mdi:shield-check"
                }
            )
            _LOGGER.debug("[Gold %s] Notifica ARMED (%s) inviata", self._row_id, profile)
        except Exception as e:
            _LOGGER.error("[Gold %s] Errore invio notifica ARMED: %s", self._row_id, e)

    async def _send_disarmed_notification(self):
        """Invia notifica DISARMED."""
        try:
            await send_multiple_notifications(
                self.hass,
                message=f"🔓 {self._attr_name} disarmata",
                title=f"Lince Gold - {self._attr_name} - Sistema Disarmato",
                persistent=True,
                persistent_id=f"alarm_disarmed_{self._row_id}",
                mobile=True,
                centrale_id=self._row_id,
                data={
                    "tag": f"alarm_disarmed_{self._row_id}",
                    "priority": "normal",
                    "color": "blue",
                    "notification_icon": "mdi:shield-off"
                }
            )
            _LOGGER.debug("[Gold %s] Notifica DISARMED inviata", self._row_id)
        except Exception as e:
            _LOGGER.debug("[Gold %s] Errore invio notifica DISARMED: %s", self._row_id, e)

    async def _send_pin_error_notification(self, action: str = "operazione"):
        """Invia notifica PIN errato."""
        try:
            await send_multiple_notifications(
                self.hass,
                message=f"❌ Codice errato per {self._attr_name}. {action.capitalize()} rifiutato.",
                title=f"Lince Gold - {self._attr_name} - Errore Autenticazione",
                persistent=True,
                persistent_id=f"pin_error_{self._row_id}",
                mobile=True,
                centrale_id=self._row_id,
                data={
                    "tag": f"pin_error_{self._row_id}",
                    "priority": "high",
                    "color": "red"
                }
            )
        except Exception as e:
            _LOGGER.debug("[Gold %s] Errore invio notifica PIN errato: %s", self._row_id, e)

    # ---------- Arm/Disarm commands ----------
    async def _arm_with_profile(self, profile: str, code: Optional[str]) -> None:
        """
        Esegue l'attivazione con un profilo specifico.
        
        Flusso Gold:
        1. Calcola la maschera dal profilo configurato
        2. Chiama gold_arm_disarm() che fa login + send_comm
        """
        pm = self._build_profile_masks()
        mask = pm.get(profile, 0)
        
        if mask == 0:
            self._set_error(f"Profilo '{profile}' non configurato per questa centrale Gold.")
            return
        
        # Validazione codice
        if not code or not code.isdigit():
            self._set_error("Codice non valido. Deve essere numerico.")
            await self._send_pin_error_notification("Inserimento")
            return

        # Avvia pending ARMING per UI reattiva
        self._clear_error()
        self._internal_command_active = True
        self._start_pending(
            state=AlarmControlPanelState.ARMING,
            expected_mask=mask,
            profile=profile,
            timeout=PENDING_DECAY_SECONDS,
        )

        # Esegui arm via API Gold
        try:
            success = await self._api.gold_arm_disarm(
                id_centrale=self._centrale_id,
                user_code=code,
                prog=mask
            )
            
            if success:
                _LOGGER.info("[Gold %s] Attivazione profilo '%s' (mask=%d) completata", 
                           self._row_id, profile, mask)
                # Aggiorna pending a stato finale
                self._pending_state = self._mask_to_ha_state_by_profiles(mask)
                self.async_write_ha_state()
                
                # Notifica
                await self._send_armed_notification(profile)
            else:
                self._clear_pending(write_state=True)
                self._set_error("Attivazione Gold fallita. Controlla il codice o riprova.")
                await self._send_pin_error_notification("Attivazione")
                
        except Exception as e:
            self._clear_pending(write_state=True)
            self._set_error(f"Errore durante attivazione Gold: {e}")
            _LOGGER.error("[Gold %s] Errore arm: %s", self._row_id, e, exc_info=True)

    async def async_alarm_disarm(self, code: Optional[str] = None) -> None:
        """Disarma l'allarme Gold."""
        # Validazione codice
        if not code or not code.isdigit():
            self._set_error("Codice non valido. Deve essere numerico.")
            await self._send_pin_error_notification("Disinserimento")
            return

        # Avvia pending DISARMING per UI reattiva
        self._clear_error()
        self._internal_command_active = True
        self._start_pending(
            state=AlarmControlPanelState.DISARMING,
            expected_mask=0,
            profile="disarm",
            timeout=PENDING_DECAY_SECONDS,
        )

        # Esegui disarm via API Gold (prog=0)
        try:
            success = await self._api.gold_arm_disarm(
                id_centrale=self._centrale_id,
                user_code=code,
                prog=0  # 0 = disarm
            )
            
            if success:
                _LOGGER.info("[Gold %s] Disattivazione completata", self._row_id)
                # Aggiorna pending a DISARMED
                self._pending_state = AlarmControlPanelState.DISARMED
                self.async_write_ha_state()
                
                # Pulisci notifica TRIGGERED se presente
                try:
                    await dismiss_persistent_notification(
                        self.hass,
                        f"alarm_triggered_{self._row_id}"
                    )
                except Exception:
                    pass
                
                # Notifica DISARMED
                await self._send_disarmed_notification()
            else:
                self._clear_pending(write_state=True)
                self._set_error("Disattivazione Gold fallita. Controlla il codice o riprova.")
                await self._send_pin_error_notification("Disattivazione")
                
        except Exception as e:
            self._clear_pending(write_state=True)
            self._set_error(f"Errore durante disattivazione Gold: {e}")
            _LOGGER.error("[Gold %s] Errore disarm: %s", self._row_id, e, exc_info=True)

    async def async_alarm_arm_home(self, code: Optional[str] = None) -> None:
        await self._arm_with_profile("home", code)

    async def async_alarm_arm_away(self, code: Optional[str] = None) -> None:
        await self._arm_with_profile("away", code)

    async def async_alarm_arm_night(self, code: Optional[str] = None) -> None:
        await self._arm_with_profile("night", code)

    async def async_alarm_arm_vacation(self, code: Optional[str] = None) -> None:
        await self._arm_with_profile("vacation", code)