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
from ..const import MANUFACTURER
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
    
    # Registra il pannello nell'API per aggiornamenti da binary_sensor
    if not hasattr(api, 'alarm_panels'):
        api.alarm_panels = {}
    api.alarm_panels[row_id] = panel
    _LOGGER.debug(f"[Gold {row_id}] Alarm panel registrato nell'API")
    
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
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._row_id))},
            name=self._centrale_name,
            manufacturer=MANUFACTURER,
            model="Lince Gold",
        )

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

    # ---------- Parsing stato Gold ----------
    def _get_gold_state(self) -> Optional[dict]:
        """
        Recupera lo stato Gold dalla cache dell'API.
        Equivalente a _get_system().get("socket_message") di Europlus.
        """
        if hasattr(self._api, '_states_cache'):
            return self._api._states_cache.get(self._row_id)
        return None
    
    def _parse_gold_status(self, state: Optional[dict]) -> tuple:
        """
        Parser specifico Gold.
        
        Ritorna: (mask, progs_any, alarm_triggered)
        
        - mask: bitmask dei programmi attivi (G1=1, G2=2, G3=4)
        - progs_any: True se almeno un programma attivo
        - alarm_triggered: True se allarme in corso
        
        NOTA: Gold non ha timer uscita/ingresso visibili nel protocollo attuale,
        quindi ARMING e PENDING non sono gestiti come in Europlus.
        """
        if not state:
            return 0, False, False
        
        try:
            prog = state.get("prog", {})
            if isinstance(prog, dict):
                g1 = bool(prog.get("g1", False))
                g2 = bool(prog.get("g2", False))
                g3 = bool(prog.get("g3", False))
            else:
                # Se prog è ancora un int (non parsato)
                g1 = bool(prog & 1)
                g2 = bool(prog & 2)
                g3 = bool(prog & 4)
            
            # Calcola mask
            mask = 0
            if g1:
                mask |= PROGRAM_BITS.get("G1", 1)
            if g2:
                mask |= PROGRAM_BITS.get("G2", 2)
            if g3:
                mask |= PROGRAM_BITS.get("G3", 4)
            
            progs_any = g1 or g2 or g3
            
            # ATTENZIONE: "allarme_inserito" significa "sistema armato" (armed), NON "allarme scattato"!
            # Per TRIGGERED dobbiamo controllare gli allarmi REALI:
            # - allarme_a, allarme_k, allarme_tecnologico in 'alim'
            # - memoria_allarme_ingressi in 'stato'
            alarm_triggered = False
            
            alim = state.get("alim", {})
            if isinstance(alim, dict):
                # Allarmi attivi in alim
                alarm_triggered = (
                    bool(alim.get("allarme_a", False)) or
                    bool(alim.get("allarme_k", False)) or
                    bool(alim.get("allarme_tecnologico", False))
                )
            
            stato = state.get("stato", {})
            if isinstance(stato, dict):
                # Anche memoria allarme indica triggered recente
                alarm_triggered = alarm_triggered or bool(stato.get("memoria_allarme_ingressi", False))
            
            _LOGGER.debug(
                f"[Gold {self._row_id}] _parse_gold_status: mask={mask}, progs_any={progs_any}, "
                f"triggered={alarm_triggered}, g1={g1}, g2={g2}, g3={g3}"
            )
            
            return mask, progs_any, alarm_triggered
            
        except Exception as e:
            _LOGGER.debug("[Gold %s] _parse_gold_status error: %s", self._row_id, e)
            return 0, False, False

    # ---------- Stato ----------
    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """
        Determina lo stato dell'allarme Gold.
        
        Ordine priorità:
        1) TRIGGERED se allarme in corso
        2) Pending DISARMING (UI reattiva durante disinserimento)
        3) Pending ARMING (UI reattiva durante inserimento) - PRIMA di DISARMED!
        4) DISARMED se nessun programma attivo
        5) ARMED_* se almeno un programma attivo
        6) Fallback al pending locale
        
        NOTA: Gold non ha timer uscita/ingresso nel protocollo,
        quindi ARMING viene mostrato tramite pending state.
        """
        # Leggi stato dalla cache API
        gold_state = self._get_gold_state()
        mask, progs_any, alarm_triggered = self._parse_gold_status(gold_state)
        
        # 1) TRIGGERED ha massima priorità
        if alarm_triggered:
            return AlarmControlPanelState.TRIGGERED
        
        # 2) Priorità al pending DISARMING
        if self._pending_state == AlarmControlPanelState.DISARMING:
            return (
                AlarmControlPanelState.DISARMED
                if not progs_any
                else AlarmControlPanelState.DISARMING
            )
        
        # 3) Priorità al pending ARMING - PRIMA di DISARMED!
        #    Così mostriamo ARMING anche se WS non ha ancora aggiornato
        if self._pending_state == AlarmControlPanelState.ARMING:
            # Se WS ha già confermato l'inserimento, mostra ARMED_*
            if progs_any:
                mapped = self._mask_to_ha_state_by_profiles(mask)
                if mapped:
                    # Pending confermato dal WS, pulisci
                    self._clear_pending()
                    return mapped
            # WS non ha ancora confermato, mostra ARMING
            return AlarmControlPanelState.ARMING
        
        # 4) DISARMED: nessun programma attivo
        if not progs_any:
            return AlarmControlPanelState.DISARMED
        
        # 5) ARMED_*: almeno un programma attivo
        if progs_any:
            mapped = self._mask_to_ha_state_by_profiles(mask)
            return mapped or AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        
        # 6) Fallback al pending locale
        if self._pending_state is not None:
            return self._pending_state
        
        return None

    def update_from_programs(self, g1: bool, g2: bool, g3: bool):
        """
        Callback per notifica che i programmi sono cambiati.
        Chiamato da update_gold_buscomm_binarysensors quando cambia g1/g2/g3.
        
        Quando il WS conferma un pending state, invio le notifiche appropriate.
        """
        # Log del cambio
        _LOGGER.debug(
            f"[Gold {self._row_id}] Programs update notification: G1={g1}, G2={g2}, G3={g3}"
        )
        
        # Calcola mask per gestione pending
        mask = 0
        if g1:
            mask |= PROGRAM_BITS.get("G1", 1)
        if g2:
            mask |= PROGRAM_BITS.get("G2", 2)
        if g3:
            mask |= PROGRAM_BITS.get("G3", 4)
        
        # Se c'era un pending state, verifica se confermato
        if self._pending_state is not None:
            if self._pending_expected_mask == mask:
                _LOGGER.info(f"[Gold {self._row_id}] Pending confermato dal WS: mask={mask}")
                
                # Invia notifica in base al tipo di pending
                pending_profile = self._pending_profile
                pending_state = self._pending_state
                
                # Pulisci pending
                self._clear_pending()
                
                # Invia notifica appropriata (async via create_task)
                # Le notifiche vengono inviate nei metodi command (arm/disarm)
                # per evitare duplicati quando arriva la conferma WS.
            else:
                _LOGGER.debug(
                    f"[Gold {self._row_id}] Pending non corrisponde: "
                    f"expected={self._pending_expected_mask}, actual={mask}"
                )
        
        # Forza aggiornamento stato UI
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        attrs = {}
        
        # Stato corrente dai dati Gold
        gold_state = self._get_gold_state()
        if gold_state:
            prog = gold_state.get("prog", {})
            if isinstance(prog, dict):
                attrs["g1"] = prog.get("g1", False)
                attrs["g2"] = prog.get("g2", False)
                attrs["g3"] = prog.get("g3", False)
            else:
                attrs["g1"] = bool(prog & 1)
                attrs["g2"] = bool(prog & 2)
                attrs["g3"] = bool(prog & 4)
            
            stato = gold_state.get("stato", {})
            if isinstance(stato, dict):
                attrs["allarme_inserito"] = stato.get("allarme_inserito", False)
                attrs["servizio"] = stato.get("servizio", False)
        
        # Profili configurati
        pm = self._build_profile_masks()
        attrs["profile_masks"] = pm
        attrs["panel_brand"] = "lince-gold"
        
        # Pending state
        if self._pending_state is not None:
            attrs["pending_state"] = self._pending_state.name
            attrs["pending_expected_mask"] = self._pending_expected_mask
            attrs["pending_profile"] = self._pending_profile
        
        # Errori
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
                _LOGGER.info("[Gold %s] Attivazione profilo '%s' (mask=%d) inviata, attesa conferma WS", 
                           self._row_id, profile, mask)
                await self._send_armed_notification(profile)

                # Fallback ottimistico: aggiorna subito la cache programmi.
                # Se il WS non arriva, il pannello non resta bloccato su DISARMED.
                state_cache = getattr(self._api, "_states_cache", None)
                if isinstance(state_cache, dict):
                    current = state_cache.get(self._row_id, {}) or {}
                    prog = dict(current.get("prog", {}) or {})
                    prog["g1"] = bool(mask & PROGRAM_BITS.get("G1", 1))
                    prog["g2"] = bool(mask & PROGRAM_BITS.get("G2", 2))
                    prog["g3"] = bool(mask & PROGRAM_BITS.get("G3", 4))
                    current["prog"] = prog
                    state_cache[self._row_id] = current

                # NOTA: Lasciamo _pending_state = ARMING
                # Lo stato ARMED_* verrà mostrato quando il WS aggiorna g1/g2/g3
                # e alarm_state() rileva progs_any = True
                self.async_write_ha_state()
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
                _LOGGER.info("[Gold %s] Disattivazione inviata, attesa conferma WS", self._row_id)

                # Fallback ottimistico: azzera subito i programmi in cache.
                state_cache = getattr(self._api, "_states_cache", None)
                if isinstance(state_cache, dict):
                    current = state_cache.get(self._row_id, {}) or {}
                    current["prog"] = {"g1": False, "g2": False, "g3": False}
                    state_cache[self._row_id] = current

                # NOTA: Lasciamo _pending_state = DISARMING
                # Lo stato DISARMED verrà mostrato quando il WS aggiorna g1/g2/g3=False
                # e alarm_state() rileva progs_any = False
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