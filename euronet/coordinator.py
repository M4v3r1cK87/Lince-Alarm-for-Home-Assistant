"""
Coordinator per connessione locale EuroPlus/EuroNET.

Gestisce l'aggiornamento periodico dei dati dalla centrale locale.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional
from dataclasses import asdict

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import EuroNetClient, StatoCentrale
from .zone_config import (
    ZoneConfigFetcherSync,
    ZoneConfigs,
    ZoneFilareConfig,
    ZoneRadioConfig,
)
from .const import (
    CONF_NUM_ZONE_FILARI,
    CONF_NUM_ZONE_RADIO,
    CONF_ARM_PROFILES,
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL_MS,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_INSTALLER_CODE,
    DEFAULT_LOCAL_USERNAME,
)
from ..utils import send_persistent_notification, send_multiple_notifications

_LOGGER = logging.getLogger(__name__)

# Intervallo di polling di fallback (usato se non configurato)
DEFAULT_UPDATE_INTERVAL = timedelta(milliseconds=DEFAULT_POLLING_INTERVAL_MS)

# Configurazione retry per caricamento zone
ZONE_CONFIG_RETRY_DELAY = 60  # Secondi tra un retry e l'altro
ZONE_CONFIG_MAX_RETRIES = 10  # Numero massimo di retry automatici

# Logger separato per il DataUpdateCoordinator base (per silenziare "Finished fetching")
# Questo evita lo spam nei log ogni polling cycle
_COORDINATOR_LOGGER = logging.getLogger(__name__ + ".polling")
_COORDINATOR_LOGGER.setLevel(logging.WARNING)  # Solo warning e superiori


class EuroNetCoordinator(DataUpdateCoordinator):
    """Coordinator per gestire l'aggiornamento dati dalla centrale locale."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: EuroNetClient,
        config_entry: ConfigEntry,
    ) -> None:
        """Inizializza il coordinator."""
        # Calcola l'intervallo di polling dalla configurazione
        polling_ms = config_entry.options.get(
            CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL_MS
        )
        update_interval = timedelta(milliseconds=polling_ms)
        
        # Usa un logger separato con livello WARNING per evitare spam
        # Il log "Finished fetching" del DataUpdateCoordinator base non apparirà
        super().__init__(
            hass,
            _COORDINATOR_LOGGER,
            name="EuroNET",
            update_interval=update_interval,
        )
        self.client = client
        self.config_entry = config_entry
        self._systems: list[dict] = []
        
        # Cache configurazione zone (caricata una volta all'avvio/reload)
        self._zone_configs: Optional[ZoneConfigs] = None
        self._zone_configs_loaded = False
        self._zone_configs_complete = False  # True se tutte le zone sono state caricate
        self._zone_config_retry_count = 0
        self._zone_config_retry_task: Optional[asyncio.Task] = None
        self._zone_config_lock = asyncio.Lock()  # Lock per evitare caricamenti paralleli
        
        # Lock per evitare richieste HTTP parallele alla centrale
        # La centrale non gestisce bene richieste concorrenti
        self._polling_lock = asyncio.Lock()
        
        # Stato precedente per rilevare transizioni allarme
        self._previous_alarm_state = False
        # Stato precedente ARM per rilevare transizioni arm/disarm (gstate: "G1,G2", etc.)
        self._previous_gstate: str | None = None
        
        _LOGGER.debug(
            "EuroNET coordinator inizializzato con polling interval: %dms",
            polling_ms
        )
    
    @property
    def num_zone_filari(self) -> int:
        """Numero di zone filari configurate."""
        # Controlla prima options, poi data (per compatibilità)
        return self.config_entry.options.get(
            CONF_NUM_ZONE_FILARI,
            self.config_entry.data.get(CONF_NUM_ZONE_FILARI, 0)
        )
    
    @property
    def num_zone_radio(self) -> int:
        """Numero di zone radio configurate."""
        # Controlla prima options, poi data (per compatibilità)
        return self.config_entry.options.get(
            CONF_NUM_ZONE_RADIO,
            self.config_entry.data.get(CONF_NUM_ZONE_RADIO, 0)
        )
    
    @property
    def arm_profiles(self) -> dict:
        """Profili ARM configurati."""
        return self.config_entry.options.get(CONF_ARM_PROFILES, {})
    
    @property
    def zone_configs(self) -> Optional[ZoneConfigs]:
        """Configurazioni complete delle zone."""
        return self._zone_configs
    
    def reset_zone_configs_cache(self) -> None:
        """Resetta la cache delle configurazioni zone per forzare un reload.
        
        Chiamare questo metodo quando il codice installatore viene modificato
        o quando è necessario ricaricare le configurazioni.
        """
        # Cancella eventuale task di retry in corso
        if self._zone_config_retry_task and not self._zone_config_retry_task.done():
            self._zone_config_retry_task.cancel()
            self._zone_config_retry_task = None
        
        self._zone_configs = None
        self._zone_configs_loaded = False
        self._zone_configs_complete = False
        self._zone_config_retry_count = 0
        _LOGGER.debug("Cache configurazioni zone resettata")
    
    def update_polling_interval(self, polling_ms: int) -> None:
        """Aggiorna l'intervallo di polling dinamicamente.
        
        Args:
            polling_ms: Nuovo intervallo in millisecondi
        """
        new_interval = timedelta(milliseconds=polling_ms)
        if self.update_interval != new_interval:
            self.update_interval = new_interval
            _LOGGER.debug("Polling interval aggiornato a %dms", polling_ms)
    
    async def _send_triggered_notification(self, system_data: dict) -> None:
        """Invia notifica quando scatta l'allarme.
        
        Questa notifica è SEMPRE inviata (force=True) indipendentemente
        dal flag notifiche, in quanto è critica per la sicurezza.
        
        Include:
        - Zone aperte (possibile causa dell'allarme)
        - Zone in allarme (allarme_24h, memoria_24h, memoria_allarme)
        - Cause dell'allarme (memorie sabotaggi e integrità)
        """
        # Raccogli zone in allarme
        zone_aperte = []
        zone_memoria_allarme = []
        zone_24h = []
        zone_memoria_24h = []
        
        entries = system_data.get("entries", {})
        _LOGGER.debug("Analisi zone per notifica TRIGGERED: %d entries totali", len(entries))
        
        for key, zona in entries.items():
            if not isinstance(zona, dict):
                continue
            
            # Ottieni nome zona (con fallback)
            numero = zona.get("numero", "?")
            nome = zona.get("nome")
            if not nome:
                if "filare" in key:
                    nome = f"Zona Filare {numero}"
                elif "radio" in key:
                    nome = f"Zona Radio {numero}"
                else:
                    nome = f"Zona {numero}"
            
            # Log per debug
            _LOGGER.debug(
                "Zona %s: aperta=%s, allarme_24h=%s, memoria_allarme=%s, memoria_24h=%s",
                nome, zona.get("aperta"), zona.get("allarme_24h"), 
                zona.get("memoria_allarme"), zona.get("memoria_24h")
            )
            
            # Controlla i flag di allarme
            if zona.get("aperta", False):
                zone_aperte.append(nome)
            if zona.get("allarme_24h", False):
                zone_24h.append(nome)
            if zona.get("memoria_24h", False):
                zone_memoria_24h.append(nome)
            if zona.get("memoria_allarme", False):
                zone_memoria_allarme.append(nome)
        
        # Log riepilogo zone trovate
        _LOGGER.debug(
            "TRIGGERED notifica - Zone aperte: %d, Zone 24h: %d, Zone memoria_24h: %d, Zone memoria_allarme: %d",
            len(zone_aperte), len(zone_24h), len(zone_memoria_24h), len(zone_memoria_allarme)
        )
        if zone_memoria_allarme:
            _LOGGER.debug("Zone in allarme: %s", ", ".join(zone_memoria_allarme))
        
        # Raccogli cause allarme dalle memorie centrale
        cause_allarme = []
        if system_data.get("memoria_integrita_bus", False):
            cause_allarme.append("🔌 Memoria integrità bus")
        if system_data.get("memoria_sabotaggio_centrale", False):
            cause_allarme.append("🔓 Sabotaggio centrale")
        if system_data.get("memoria_sabotaggio_dispositivi_bus", False):
            cause_allarme.append("🔓 Sabotaggio dispositivi bus")
        if system_data.get("memoria_sabotaggio_ingressi", False):
            cause_allarme.append("🔓 Sabotaggio ingressi")
        if system_data.get("allarme_integrita_bus", False):
            cause_allarme.append("⚠️ Allarme integrità bus")
        if system_data.get("sabotaggio_centrale", False):
            cause_allarme.append("🚨 Sabotaggio centrale in corso")
        if system_data.get("sabotaggio_ingressi", False):
            cause_allarme.append("🚨 Sabotaggio ingressi in corso")
        if system_data.get("sabotaggio_dispositivi_bus", False):
            cause_allarme.append("🚨 Sabotaggio dispositivi bus in corso")
        
        # Costruisci messaggio
        lines = ["🚨 **ALLARME SCATTATO** 🚨\n"]
        
        # Zone aperte (possibile causa allarme)
        if zone_aperte:
            lines.append("**Zone aperte (possibile causa):**")
            for z in zone_aperte:
                lines.append(f"  • {z}")
            lines.append("")
        
        # Zone in allarme attivo (24h)
        if zone_24h:
            lines.append("**Zone in allarme 24h:**")
            for z in zone_24h:
                lines.append(f"  • {z}")
            lines.append("")
        
        # Zone con memoria allarme
        if zone_memoria_allarme:
            lines.append("**Zone con memoria allarme:**")
            for z in zone_memoria_allarme:
                lines.append(f"  • {z}")
            lines.append("")
        
        # Zone con memoria 24h
        if zone_memoria_24h:
            lines.append("**Zone con memoria 24h:**")
            for z in zone_memoria_24h:
                lines.append(f"  • {z}")
            lines.append("")
        
        # Cause allarme
        if cause_allarme:
            lines.append("**Cause allarme:**")
            for c in cause_allarme:
                lines.append(f"  {c}")
            lines.append("")
        
        # Se non ci sono dettagli specifici
        if not zone_aperte and not zone_24h and not zone_memoria_allarme and not zone_memoria_24h and not cause_allarme:
            lines.append("Allarme generico rilevato - verificare centrale")
        
        message = "\n".join(lines)
        
        # Invia notifica con force=True (ignora flag notifiche)
        await send_multiple_notifications(
            self.hass,
            message=message,
            title="🚨 ALLARME - Centrale Lince",
            persistent=True,
            persistent_id=f"lince_alarm_triggered_{self.client.host}",
            mobile=True,
            centrale_id=self.client.host,
            force=True,  # SEMPRE inviare, ignora flag notifiche
            data={
                "tag": "lince_alarm_triggered",
                "importance": "max",
                "priority": "high",
                "channel": "alarm_critical",
                "ttl": 0,
                "vibrationPattern": "100, 200, 100, 200, 100, 200, 100, 200",
                "ledColor": "red",
                "actions": [
                    {"action": "URI", "title": "Apri Home Assistant", "uri": "/lovelace"}
                ]
            }
        )
        _LOGGER.warning("Notifica ALLARME SCATTATO inviata per %s", self.client.host)
    
    def _get_mode_name_from_gstate(self, gstate: str) -> str:
        """Determina il nome del modo dai programmi attivi."""
        if not gstate:
            return "Disarmato"
        
        # Ottieni i profili configurati
        arm_profiles = self.arm_profiles
        active_set = set(p.strip() for p in gstate.split(",") if p.strip())
        
        # Cerca corrispondenza con i profili configurati
        mode_names = {
            "away": "Armato Totale",
            "home": "Armato Casa",
            "night": "Armato Notte",
            "vacation": "Armato Vacanza",
        }
        
        for mode, name in mode_names.items():
            configured = arm_profiles.get(mode, [])
            if configured:
                configured_set = set(p.upper() for p in configured)
                if configured_set == active_set:
                    return name
        
        # Fallback: mostra programmi attivi
        if active_set:
            return f"Armato ({gstate})"
        return "Disarmato"
    
    async def _send_arm_disarm_notification(self, prev_gstate: str, curr_gstate: str, system_data: dict) -> None:
        """Invia notifica per cambio stato ARM/DISARM.
        
        Questa notifica rispetta il flag notifiche (force=False).
        """
        prev_mode = self._get_mode_name_from_gstate(prev_gstate)
        curr_mode = self._get_mode_name_from_gstate(curr_gstate)
        
        # Determina se è un ARM o DISARM
        if not curr_gstate:
            # DISARM
            icon = "🔓"
            title = "Allarme Disarmato"
            message = f"{icon} Centrale disarmata\n\nStato precedente: {prev_mode}"
        else:
            # ARM
            icon = "🔒"
            title = "Allarme Armato"
            if prev_gstate:
                # Cambio da un modo armato a un altro
                message = f"{icon} Centrale armata: **{curr_mode}**\n\nStato precedente: {prev_mode}"
            else:
                # Passaggio da disarmato a armato
                message = f"{icon} Centrale armata: **{curr_mode}**"
        
        _LOGGER.debug("Cambio stato allarme: %s -> %s", prev_mode, curr_mode)
        
        # Invia notifica (rispetta flag notifiche)
        await send_multiple_notifications(
            self.hass,
            message=message,
            title=f"{icon} {title} - Centrale Lince",
            persistent=False,
            mobile=True,
            centrale_id=self.client.host,
            force=False,  # Rispetta il flag notifiche
        )

    async def _schedule_zone_config_retry(self) -> None:
        """Programma un retry per il caricamento delle zone mancanti.
        
        Questo metodo tenta di caricare le zone mancanti in background.
        Non forza più un reload dell'integrazione - le zone verranno
        aggiornate al prossimo reload manuale.
        """
        if self._zone_config_retry_count >= ZONE_CONFIG_MAX_RETRIES:
            _LOGGER.info(
                "Raggiunto il limite massimo di retry (%d) per caricamento zone. "
                "Ricarica manualmente l'integrazione per riprovare.",
                ZONE_CONFIG_MAX_RETRIES
            )
            return
        
        self._zone_config_retry_count += 1
        
        await asyncio.sleep(ZONE_CONFIG_RETRY_DELAY)
        
        # Reset per permettere un nuovo tentativo
        self._zone_configs_loaded = False
        
        # Esegui il caricamento (passiamo from_retry=True)
        await self._async_load_zone_configs(from_retry=True)
        
        # Verifica se dobbiamo programmare un altro retry
        if self._zone_configs:
            num_filari = self.num_zone_filari
            num_radio = self.num_zone_radio
            loaded_filari = len(self._zone_configs.zone_filari)
            loaded_radio = len(self._zone_configs.zone_radio)
            
            if (loaded_filari < num_filari or loaded_radio < num_radio) and self._zone_config_retry_count < ZONE_CONFIG_MAX_RETRIES:
                self._zone_config_retry_task = asyncio.create_task(
                    self._schedule_zone_config_retry()
                )
        
    async def _async_load_zone_configs(self, from_retry: bool = False) -> None:
        """Carica le configurazioni complete delle zone usando il codice installatore.
        
        Questo metodo viene chiamato una sola volta durante l'inizializzazione
        o durante il reload dell'integrazione. Usa ZoneConfigFetcherSync per
        recuperare tutti i dati di configurazione delle zone filari e radio
        dalla centrale tramite web scraping. La nuova classe usa la stessa
        sessione HTTP del client principale, evitando conflitti di sessione.
        
        Args:
            from_retry: Se True, siamo in un retry e non creiamo nuovi task di retry
        """
        # Usa lock per evitare caricamenti paralleli
        async with self._zone_config_lock:
            if self._zone_configs_loaded:
                return
            
            num_filari = self.num_zone_filari
            num_radio = self.num_zone_radio
            
            if num_filari == 0 and num_radio == 0:
                _LOGGER.debug("Nessuna zona configurata - salta caricamento configurazioni")
                self._zone_configs_loaded = True
                return
            
            # Recupera credenziali dalla configurazione dell'utente
            options = self.config_entry.options
            data = self.config_entry.data
            
            host = options.get(CONF_HOST) or data.get(CONF_HOST, "")
            password = options.get(CONF_PASSWORD) or data.get(CONF_PASSWORD, "")
            installer_code = options.get(CONF_INSTALLER_CODE) or data.get(CONF_INSTALLER_CODE, "")
            
            if not installer_code:
                _LOGGER.warning(
                    "Codice installatore NON configurato (vuoto='%s') - "
                    "i dettagli di configurazione delle zone non saranno disponibili. "
                    "Options keys: %s, Data keys: %s",
                    installer_code,
                    list(options.keys()),
                    list(data.keys())
                )
                self._zone_configs_loaded = True
                return
            
            if not host or not password:
                _LOGGER.warning(
                    "Credenziali incomplete - "
                    "impossibile caricare configurazione zone"
                )
                self._zone_configs_loaded = True
                return
                
            try:
                # Usa ZoneConfigFetcherSync con il client esistente
                # Questo evita conflitti di sessione (stessa sessione HTTP)
                fetcher = ZoneConfigFetcherSync(
                    client=self.client,
                    hass=self.hass,
                    num_zone_filari=num_filari,
                    num_zone_radio=num_radio,
                )
                
                # Esegui il fetch (usa la stessa sessione del client)
                new_configs = await fetcher.fetch_all_zones()
                
                # Merge con le configurazioni esistenti (per retry)
                if self._zone_configs and new_configs:
                    # Unisci le zone: le nuove si aggiungono/sovrascrivono le vecchie
                    for zona_num, zona_config in new_configs.zone_filari.items():
                        self._zone_configs.zone_filari[zona_num] = zona_config
                    for zona_num, zona_config in new_configs.zone_radio.items():
                        self._zone_configs.zone_radio[zona_num] = zona_config
                    self._zone_configs.timestamp = new_configs.timestamp
                elif new_configs:
                    self._zone_configs = new_configs
                
                # Log dei risultati e verifica completezza
                if self._zone_configs:
                    loaded_filari = len(self._zone_configs.zone_filari)
                    loaded_radio = len(self._zone_configs.zone_radio)
                    
                    _LOGGER.info(
                        "Zone configs caricate: %d/%d filari, %d/%d radio",
                        loaded_filari, num_filari,
                        loaded_radio, num_radio,
                    )
                    
                    # Verifica se tutte le zone attese sono state caricate
                    if loaded_filari >= num_filari and loaded_radio >= num_radio:
                        self._zone_configs_complete = True
                    else:
                        self._zone_configs_complete = False
                        # Programma retry automatico solo se non siamo già in un retry
                        # (il retry gestisce autonomamente il prossimo tentativo)
                        if not from_retry and self._zone_config_retry_count < ZONE_CONFIG_MAX_RETRIES:
                            self._zone_config_retry_task = asyncio.create_task(
                                self._schedule_zone_config_retry()
                            )
                else:
                    self._zone_configs_complete = False
                    _LOGGER.warning("Nessuna configurazione zone caricata")
                    # Programma retry automatico solo se non siamo già in un retry
                    if not from_retry and self._zone_config_retry_count < ZONE_CONFIG_MAX_RETRIES:
                        self._zone_config_retry_task = asyncio.create_task(
                            self._schedule_zone_config_retry()
                        )
                
                self._zone_configs_loaded = True
                # Non serve più invalidare la sessione: ZoneConfigFetcherSync
                # usa la stessa sessione del client principale
                
            except Exception as e:
                _LOGGER.error("Errore caricamento configurazioni zone: %s", e)
                self._zone_configs_loaded = True
                # Programma retry anche in caso di errore (solo se non siamo già in un retry)
                if not from_retry and self._zone_config_retry_count < ZONE_CONFIG_MAX_RETRIES:
                    self._zone_config_retry_task = asyncio.create_task(
                        self._schedule_zone_config_retry()
                    )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch data dalla centrale locale.
        
        NOTA: Il polling usa solo HTTP Basic Auth (già configurato nella sessione).
        NON richiede il login con codice installatore - quello serve solo per:
        - Caricare configurazioni zone (all'avvio/reload)
        - Eseguire comandi arm/disarm
        
        Usa un lock per evitare richieste parallele alla centrale che potrebbero
        saturare i log e sovraccaricare il dispositivo.
        """
        # Se c'è già un polling in corso, salta questo ciclo
        # Questo evita l'accumulo di richieste quando la centrale è lenta o offline
        if self._polling_lock.locked():
            # Ritorna i dati precedenti se disponibili, altrimenti solleva errore
            if self._systems:
                return self._systems
            raise UpdateFailed("Polling già in corso")
        
        async with self._polling_lock:
            try:
                # Esegui operazioni sincrone in executor
                # get_stato_centrale usa HTTP Basic Auth, non richiede codice installatore
                stato = await self.hass.async_add_executor_job(
                    self.client.get_stato_centrale
                )
                
                if not stato:
                    # Errore di comunicazione (rete, timeout, centrale occupata)
                    # NON è un problema di login con codice - non tentare re-login
                    raise UpdateFailed("Impossibile leggere stato centrale")
            
                # Leggi zone filari
                zone_filari = await self.hass.async_add_executor_job(
                    self.client.get_stato_zone_filari
                )
                
                # Leggi zone radio (tutti i gruppi necessari)
                zone_radio = []
                if self.num_zone_radio > 0:
                    # Calcola quanti gruppi leggere (10 zone per gruppo)
                    num_gruppi = (self.num_zone_radio + 9) // 10  # arrotonda per eccesso
                    for gruppo in range(num_gruppi):
                        zone_gruppo = await self.hass.async_add_executor_job(
                            self.client.get_stato_zone_radio, gruppo
                        )
                        zone_radio.extend(zone_gruppo)
                
                # Costruisci struttura dati compatibile con l'integrazione esistente
                # Simuliamo un "sistema" cloud-like per compatibilità
                system_data = self._build_system_data(stato, zone_filari, zone_radio)
                
                # Rileva transizione a stato ALLARME e invia notifica
                current_alarm_state = system_data.get("allarme", False)
                if current_alarm_state and not self._previous_alarm_state:
                    # Transizione da non-allarme a allarme -> TRIGGERED!
                    _LOGGER.warning("Rilevato allarme scattato! Invio notifica...")
                    # Schedula invio notifica (non bloccare l'update)
                    self.hass.async_create_task(
                        self._send_triggered_notification(system_data)
                    )
                self._previous_alarm_state = current_alarm_state
                
                # Rileva transizione ARM/DISARM (indipendentemente dalla fonte)
                current_gstate = system_data.get("gstate", "")
                if self._previous_gstate is not None and current_gstate != self._previous_gstate:
                    # Lo stato è cambiato - invia notifica appropriata
                    self.hass.async_create_task(
                        self._send_arm_disarm_notification(self._previous_gstate, current_gstate, system_data)
                    )
                self._previous_gstate = current_gstate
                
                self._systems = [system_data]
                
                # IMPORTANTE: restituisce direttamente la lista dei sistemi
                # per compatibilità con le piattaforme che iterano su coordinator.data
                return self._systems
                
            except UpdateFailed:
                # Re-raise senza log aggiuntivo (già loggato sopra)
                raise
            except Exception as e:
                _LOGGER.error(f"Errore aggiornamento dati locali: {e}")
                raise UpdateFailed(f"Errore comunicazione: {e}")
    
    def _build_system_data(self, stato: StatoCentrale, zone_filari: list, zone_radio: list | None = None) -> dict:
        """Costruisce struttura dati sistema compatibile con cloud."""
        # Mappiamo lo stato locale a una struttura simile a quella cloud
        # per minimizzare le modifiche alle entità esistenti
        
        if zone_radio is None:
            zone_radio = []
        
        # Determina lo stato generale
        gstate = []
        if stato.g1:
            gstate.append("G1")
        if stato.g2:
            gstate.append("G2")
        if stato.g3:
            gstate.append("G3")
        if stato.gext:
            gstate.append("GEXT")
        
        # Numero di zone configurate dall'utente
        num_filari = self.num_zone_filari
        num_radio = self.num_zone_radio
            
        # Costruisci entries per le zone (solo quelle configurate)
        entries = {}
        for zona in zone_filari:
            # Filtra: includi solo zone fino al numero configurato
            if zona.numero > num_filari:
                continue
                
            # Usa chiave zona_filare_X per distinguere da zone radio
            entry_key = f"zona_filare_{zona.numero}"
            
            # Recupera configurazione dalla cache (se disponibile)
            zone_config = None
            nome = None  # None = nome non trovato, userà fallback nel binary_sensor
            if self._zone_configs and zona.numero in self._zone_configs.zone_filari:
                zone_config = self._zone_configs.zone_filari[zona.numero]
                # Usa il nome solo se è un nome personalizzato (non "INGRESSO XX")
                if zone_config.is_configured:
                    nome = zone_config.nome
            
            # Costruisci entry con stato runtime
            entry_data = {
                "numero": zona.numero,
                "nome": nome,
                "aperta": zona.aperta,
                "esclusa": zona.esclusa,
                "allarme_24h": zona.allarme_24h,
                "memoria_24h": zona.memoria_24h,
                "memoria_allarme": zona.memoria_allarme,
            }
            
            # Aggiungi attributi di configurazione se disponibili
            if zone_config:
                entry_data["config"] = {
                    "tipo": zone_config.tipo_label,
                    "trigger": zone_config.trigger_label,
                    "logica": zone_config.logica_label,
                    "numero_allarmi": zone_config.numero_allarmi_label,
                    "tempo_ingresso": zone_config.tempo_ingresso_totale,
                    "tempo_uscita": zone_config.tempo_uscita_totale,
                    "programmi": [k for k, v in zone_config.programmi.items() if v],
                    "parzializzabile": zone_config.parzializzabile,
                    "ritardato": zone_config.ritardato,
                    "silenzioso": zone_config.silenzioso,
                    "test": zone_config.test,
                    "ronda": zone_config.ronda,
                    "h24": zone_config.h24,
                    "percorso": zone_config.percorso,
                    "uscita_a": zone_config.uscita_a,
                    "uscita_k": zone_config.uscita_k,
                    "fuoco": zone_config.fuoco,
                    "campanello": zone_config.campanello,
                    "elettroserratura": zone_config.elettroserratura,
                }
            
            entries[entry_key] = entry_data
        
        # Costruisci mappa zone radio per lookup veloce (numero -> StatoZonaRadio)
        zone_radio_map = {z.numero: z for z in zone_radio}
        
        # Aggiungi zone radio (se configurate) con stato runtime reale
        if num_radio > 0:
            for numero in range(1, num_radio + 1):
                entry_key = f"zona_radio_{numero}"
                
                # Recupera stato runtime dalla mappa
                stato_zona = zone_radio_map.get(numero)
                
                # Recupera configurazione dalla cache (se disponibile)
                zone_config = None
                nome = None
                if self._zone_configs and numero in self._zone_configs.zone_radio:
                    zone_config = self._zone_configs.zone_radio[numero]
                    # Usa il nome solo se è configurato (non "Non Disponibile")
                    if zone_config.is_configured:
                        nome = zone_config.nome
                
                entry_data = {
                    "numero": numero,
                    "nome": nome,
                    "tipo": "radio",
                    # Stato runtime reale dal client
                    "aperta": stato_zona.aperta if stato_zona else False,
                    "esclusa": zone_config.escluso if zone_config else False,
                    "allarme_24h": stato_zona.allarme_24h if stato_zona else False,
                    "memoria_24h": stato_zona.memoria_24h if stato_zona else False,
                    "memoria_allarme": stato_zona.memoria_allarme if stato_zona else False,
                    "supervisione": stato_zona.supervisione if stato_zona else False,
                    "batteria_scarica": stato_zona.batteria_scarica if stato_zona else False,
                }
                
                # Aggiungi configurazione se disponibile
                if zone_config:
                    entry_data["config"] = {
                        "supervisionato": zone_config.supervisionato,
                        "escluso": zone_config.escluso,
                        "associazioni_filari": zone_config.associazioni_filari,
                        "associazione_26_31": zone_config.associazione_26_31,
                        "associazione_27_32": zone_config.associazione_27_32,
                        "associazione_28_33": zone_config.associazione_28_33,
                        "associazione_29_34": zone_config.associazione_29_34,
                        "associazione_30_35": zone_config.associazione_30_35,
                    }
                    
                entries[entry_key] = entry_data
        
        return {
            "id": 1,  # ID locale fisso
            "name": "Centrale Locale",
            "id_centrale": self.client.host,
            "_detected_brand": "lince-europlus",
            "_local": True,
            
            # Stato programmi
            "gstate": ",".join(gstate) if gstate else "",
            "g1": stato.g1,
            "g2": stato.g2,
            "g3": stato.g3,
            "gext": stato.gext,
            
            # Stato generale
            "allarme": stato.allarme,
            "guasto": stato.guasto,
            "rete_220v": stato.rete_220v,
            "batteria_interna_ok": stato.batteria_interna_ok,
            "batteria_esterna_ok": stato.batteria_esterna_ok,
            "modo_servizio": stato.modo_servizio,
            
            # Sabotaggi
            "sabotaggio_centrale": stato.sabotaggio_centrale,
            "sabotaggio_ingressi": stato.sabotaggio_ingressi,
            "sabotaggio_dispositivi_bus": stato.sabotaggio_dispositivi_bus,
            "allarme_integrita_bus": stato.allarme_integrita_bus,
            
            # Memorie sabotaggi
            "memoria_sabotaggio_centrale": stato.memoria_sabotaggio_centrale,
            "memoria_sabotaggio_ingressi": stato.memoria_sabotaggio_ingressi,
            "memoria_sabotaggio_dispositivi_bus": stato.memoria_sabotaggio_dispositivi_bus,
            "memoria_integrita_bus": stato.memoria_integrita_bus,
            
            # Valori
            "tensione_batteria": stato.tensione_batteria,
            "tensione_bus": stato.tensione_bus,
            "temperatura": stato.temperatura,
            "release_sw": stato.release_sw,
            # Alias per compatibilità con entities.py
            "tensione_batteria_v": stato.tensione_batteria,
            "tensione_bus_v": stato.tensione_bus,
            "temperatura_c": stato.temperatura,
            
            # Espansioni
            "espansione_1": stato.espansione_1,
            "espansione_2": stato.espansione_2,
            "espansione_3": stato.espansione_3,
            "espansione_4": stato.espansione_4,
            "espansione_5": stato.espansione_5,
            "espansione_radio": stato.espansione_radio,
            
            # Zone
            "entries": entries,
            "ingressi_aperti": stato.ingressi_aperti,
            "ingressi_esclusi": stato.ingressi_esclusi,
            
            # Configurazione zone
            "num_zone_filari": num_filari,
            "num_zone_radio": num_radio,
            
            # Profili ARM configurati
            "arm_profiles": self.arm_profiles,
            
            # Compatibilità cloud
            "access_data": {},
            "datetime": stato.datetime,
        }
    
    @property
    def systems(self) -> list[dict]:
        """Restituisce la lista dei sistemi."""
        return self._systems
    
    async def async_arm(self, code: str, programs: list[str], arm_mode: str = "away") -> bool:
        """Arma i programmi specificati.
        
        Args:
            code: Codice utente inserito nel pannello allarme
            programs: Lista programmi da armare
            arm_mode: Modalità di armamento (away, home, night, vacation)
        """
        if not code:
            _LOGGER.error("Codice utente non fornito")
            return False
            
        try:
            result = await self.hass.async_add_executor_job(
                self.client.arm, code, programs
            )
            if result:
                await self.async_request_refresh()
                
                # Invia notifica di armamento (rispetta lo switch notifiche)
                mode_names = {
                    "away": "Fuori casa",
                    "home": "In casa", 
                    "night": "Notte",
                    "vacation": "Vacanza"
                }
                mode_name = mode_names.get(arm_mode, arm_mode.capitalize())
                
                await send_multiple_notifications(
                    self.hass,
                    message=f"Centrale armata in modalità **{mode_name}**",
                    title="🔒 Allarme Attivato",
                    persistent=True,
                    persistent_id=f"lince_alarm_armed_{self.client.host}",
                    mobile=True,
                    centrale_id=self.client.host,  # Usa host per controllare le notifiche
                    data={
                        "tag": "lince_alarm_status",
                        "importance": "high",
                        "channel": "alarm",
                        "actions": [
                            {"action": "URI", "title": "Apri Home Assistant", "uri": "/lovelace"}
                        ]
                    }
                )
            return result
        except Exception as e:
            _LOGGER.error(f"Errore arm: {e}")
            return False
    
    async def async_disarm(self, code: str) -> bool:
        """Disarma tutti i programmi.
        
        Args:
            code: Codice utente inserito nel pannello allarme
        """
        if not code:
            _LOGGER.error("Codice utente non fornito")
            return False
            
        try:
            result = await self.hass.async_add_executor_job(
                self.client.disarm, code
            )
            if result:
                await self.async_request_refresh()
                
                # Invia notifica di disarmo (rispetta lo switch notifiche)
                await send_multiple_notifications(
                    self.hass,
                    message="Centrale disarmata",
                    title="🔓 Allarme Disattivato",
                    persistent=True,
                    persistent_id=f"lince_alarm_armed_{self.client.host}",
                    mobile=True,
                    centrale_id=self.client.host,  # Usa host per controllare le notifiche
                    data={
                        "tag": "lince_alarm_status",
                        "importance": "default",
                        "channel": "alarm"
                    }
                )
            return result
        except Exception as e:
            _LOGGER.error(f"Errore disarm: {e}")
            return False

    async def async_shutdown(self) -> None:
        """Cancella task in background, ferma il polling e pulisce le risorse."""
        _LOGGER.debug("Shutdown EuroNET coordinator...")
        
        # Ferma gli aggiornamenti periodici
        self.update_interval = None
        
        # Cancella task retry zone config
        if self._zone_config_retry_task and not self._zone_config_retry_task.done():
            _LOGGER.debug("Cancellazione task retry zone config")
            self._zone_config_retry_task.cancel()
            try:
                await self._zone_config_retry_task
            except asyncio.CancelledError:
                pass
            self._zone_config_retry_task = None
        
        # Esegui logout dal client
        try:
            await self.hass.async_add_executor_job(self.client.logout, True)
            _LOGGER.debug("Logout EuroNET eseguito durante shutdown coordinator")
        except Exception as e:
            _LOGGER.debug(f"Errore logout durante shutdown (ignorato): {e}")
        
        _LOGGER.debug("EuroNET coordinator shutdown completato")
