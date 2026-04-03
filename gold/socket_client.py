"""Socket.IO client specifico per Lince Gold con logging completo."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional, Dict
from datetime import datetime

from ..common.socket_client import BaseSocketClient
from .parser import GoldStateParser
from .parser.device_stat_parser import parse_radio_stat, parse_bus_stat, parse_filare_stat, get_device_type_name
from ..const import API_SOCKET_IO_URL, DOMAIN
from .const import SOCKET_NAMESPACE

_LOGGER = logging.getLogger(__name__)

class GoldSocketClient(BaseSocketClient):
    """Client Socket.IO specifico per centrali Gold con debug esteso."""
    
    def __init__(self, *args, **kwargs):
        """Initialize Gold socket client."""
        super().__init__(*args, **kwargs)
        
        # Parser Gold
        self._state_parser = GoldStateParser()
        
        # Storage per debug
        self._last_messages = []
        self._max_messages = 100
        
        # Eventi Gold specifici
        self._gold_events = {}
        
        # Physical map e device stats per sensori
        self._physical_map: Dict[str, Any] = {}
        self._dev_stats: Dict[str, Dict[int, list]] = {
            "radio": {},
            "bus": {},
            "filari": {}
        }
        
        # Callback per aggiornamento sensori
        self._dev_stats_callback: Optional[Callable] = None

        # Debug: ultimo evento dev stats ricevuto
        self._last_dev_stats_ts: Optional[str] = None
        
        _LOGGER.info(f"[{self.centrale_id}] GoldSocketClient initialized")
    
    def _build_connect_url(self) -> str:
        """URL specifico Gold."""
        # Assumo stesso pattern di Europlus per ora
        url = f"{API_SOCKET_IO_URL}/?token={self.token}&system_id={self.centrale_id}"
        _LOGGER.debug(f"[{self.centrale_id}] Gold connect URL: {url}")
        return url
    
    def _get_namespace(self) -> str:
        """Namespace specifico Gold."""
        _LOGGER.debug(f"[{self.centrale_id}] Gold namespace: {SOCKET_NAMESPACE}")
        return SOCKET_NAMESPACE
    
    def _register_handlers(self):
        """Registra TUTTI gli handler possibili per debug massivo."""
        namespace = SOCKET_NAMESPACE

        _LOGGER.info(f"[{self.centrale_id}] Registrazione handler socket su namespace '{namespace}'")
        
        # Handler base
        self.sio.on("connect", self.on_connect, namespace=namespace)
        self.sio.on("disconnect", self.on_disconnect, namespace=namespace)
        self.sio.on("connect_error", self.on_connect_error, namespace=namespace)
        
        # Handler specifici Gold
        self.sio.on("onGoldState", self.on_gold_state, namespace=namespace)
        self.sio.on("onGoldDevStats", self.on_gold_dev_stats, namespace=namespace)
        self.sio.on("onGoldSync", self.on_gold_sync, namespace=namespace)
        self.sio.on("onGoldEndSync", self.on_gold_end_sync, namespace=namespace)

        # Catch-all: logga qualunque evento arrivi sul namespace Gold.
        # Utile se il backend cambia nome evento (es. onGoldDeviceStats vs onGoldDevStats).
        self.sio.on("*", self.on_any_event, namespace=namespace)

        _LOGGER.info(
            f"[{self.centrale_id}] Handler Gold registrati: "
            "onGoldState, onGoldDevStats, onGoldSync, onGoldEndSync, *"
        )
    
    # ------------------------------ Event handlers GOLD ------------------------------
    
    async def on_connect(self):
        """Handler connessione Gold."""
        self._connected = True
        self._connected_event.set()
        self._reconnect_backoff = 2.0
        
        _LOGGER.info(f"[{self.centrale_id}] Gold Socket.IO connected")
        _LOGGER.debug(f"[{self.centrale_id}] Connection details: namespace={SOCKET_NAMESPACE}")
        _LOGGER.info(
            f"[{self.centrale_id}] In ascolto eventi Gold: "
            "onGoldState/onGoldDevStats/onGoldSync/onGoldEndSync"
        )
        
        # Log session info
        if self.sio:
            _LOGGER.debug(f"[{self.centrale_id}] Session ID: {self.sio.sid}")
        
        if self.connect_callback:
            await self.connect_callback(self.centrale_id)

        # Richiedi esplicitamente i device stats al server.
        # Alcune implementazioni server non li mandano in automatico
        # ma aspettano un emit del client.
        try:
            ns = self._get_namespace()
            _LOGGER.warning(
                f"[{self.centrale_id}] Emitting 'getDevStats' per richiedere stats dispositivi..."
            )
            await self.sio.emit("getDevStats", namespace=ns)
        except Exception as e:
            _LOGGER.debug(f"[{self.centrale_id}] emit getDevStats non riuscito (normale se non supportato): {e}")

    async def on_any_event(self, event: str, data: Any = None):
        """Catch-all per debug eventi socket non mappati esplicitamente."""
        try:
            known = {"onGoldState", "onGoldDevStats", "onGoldSync", "onGoldEndSync"}
            if event not in known:
                _LOGGER.debug(
                    f"[{self.centrale_id}] [CATCH-ALL] evento socket sconosciuto: '{event}' "
                    f"payload={str(data)[:200]}"
                )
        except Exception:
            _LOGGER.debug(f"[{self.centrale_id}] Errore nel catch-all eventi", exc_info=True)
    
    async def on_disconnect(self):
        """Handler disconnessione Gold."""
        self._connected = False
        self._connected_event.clear()
        
        _LOGGER.warning(f"[{self.centrale_id}] Gold Socket.IO disconnected")
        
        if self.disconnect_callback:
            await self.disconnect_callback(self.centrale_id)
    
    async def on_connect_error(self, data: Any = None):
        """Handler errore connessione Gold."""
        _LOGGER.error(f"[{self.centrale_id}] Gold connection error: {data}")
        
        # Log dettagliato dell'errore
        if isinstance(data, dict):
            for key, value in data.items():
                _LOGGER.debug(f"[{self.centrale_id}] Error detail - {key}: {value}")
        
        # Check autenticazione
        from ..common.socket_client import _UNAUTH_STRINGS
        msg = str(data or "").lower()
        
        if any(s in msg for s in _UNAUTH_STRINGS):
            _LOGGER.warning(f"[{self.centrale_id}] Authentication error detected")
            await self._handle_unauthorized()
        else:
            await self._schedule_reconnect_backoff("gold_connect_error")
    
    async def on_gold_state(self, data):
        """Handler specifico per stato Gold."""
        timestamp = datetime.now().isoformat()
        _LOGGER.debug(f"[{self.centrale_id}] ===== GOLD STATE RECEIVED =====")
        _LOGGER.debug(f"[{self.centrale_id}] Timestamp: {timestamp}")
        
        # Log raw data
        _LOGGER.debug(f"[{self.centrale_id}] Raw state data: {data}")

        # Inizializza parsed a None
        parsed = None
        
        # Parse con il parser
        try:
            parsed = self._state_parser.parse(data)
            
            _LOGGER.debug(f"[{self.centrale_id}] Parsed state:")
            _LOGGER.debug(f"[{self.centrale_id}]   Armed: {self._state_parser.is_armed()}")
            _LOGGER.debug(f"[{self.centrale_id}]   Programs: {self._state_parser.get_armed_programs()}")
            _LOGGER.debug(f"[{self.centrale_id}]   Battery: {self._state_parser.get_battery_voltage()}V")
            _LOGGER.debug(f"[{self.centrale_id}]   Current: {self._state_parser.get_current_consumption()}A")
            _LOGGER.debug(f"[{self.centrale_id}]   WiFi: {self._state_parser.get_wifi_status()}")
            _LOGGER.debug(f"[{self.centrale_id}]   Firmware: {self._state_parser.get_firmware_version()}")
            
            # Check problemi
            problemi = self._state_parser.get_system_problems()
            if problemi:
                _LOGGER.debug(f"[{self.centrale_id}] System problems: {', '.join(problemi)}")
            
            # Check zone aperte
            zone = self._state_parser.get_open_zones()
            zone_aperte = [k for k, v in zone.items() if v]
            if zone_aperte:
                _LOGGER.debug(f"[{self.centrale_id}] Open zones: {', '.join(zone_aperte)}")
            
            # Check allarmi
            allarmi = self._state_parser.get_active_alarms()
            if allarmi:
                _LOGGER.debug(f"[{self.centrale_id}] Active alarms: {', '.join(allarmi)}")
            
        except Exception as e:
            _LOGGER.error(f"[{self.centrale_id}] Error parsing Gold state: {e}", exc_info=True)
        
        _LOGGER.debug(f"[{self.centrale_id}] ==============================")
        
        self._store_message("onGoldState", data, timestamp)
        
        if self.message_callback:
            await self.message_callback(
                self.centrale_id, 
                {"type": "gold_state", "data": parsed if parsed is not None else data}
            )
    
    async def on_gold_dev_stats(self, data):
        """
        Handler per stato dispositivi Gold.
        
        Formato dati ricevuti:
        {"type": "radio", "group": 0, "stats": [513, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}
        """
        timestamp = datetime.now().isoformat()
        self._last_dev_stats_ts = timestamp
        _LOGGER.debug(f"[{self.centrale_id}] ===== GOLD DEV STATS RECEIVED =====")
        _LOGGER.debug(f"[{self.centrale_id}] Raw data: {data}")
        
        try:
            dev_type = data.get("type", "")  # "radio", "bus", "filari"
            group = data.get("group", 0)
            stats = data.get("stats", [])
            
            _LOGGER.debug(f"[{self.centrale_id}] Type: {dev_type}, Group: {group}, Stats count: {len(stats)}")
            
            # Salva gli stats raw
            if dev_type in self._dev_stats:
                self._dev_stats[dev_type][group] = stats
            
            # Parsa gli stats se abbiamo la physical map
            parsed_stats = {}
            pm_key = dev_type if dev_type != "filari" else "filari"
            pm_devices = self._physical_map.get(pm_key, [])
            
            # Log physical map status
            if not pm_devices:
                _LOGGER.warning(
                    f"[{self.centrale_id}] Physical map vuota per {pm_key}! "
                    f"Stats ricevuti ma non possono essere parsati."
                )
            
            for i, stat_value in enumerate(stats):
                global_idx = (group * 16) + i
                
                if dev_type == "radio" and global_idx < len(pm_devices):
                    device_config = pm_devices[global_idx]
                    num_tipo = device_config.get("num_tipo_periferica", 0)
                    num_spec = device_config.get("num_spec_periferica", 0)
                    device_name = device_config.get("nome", f"Radio {global_idx}")
                    
                    # Solo dispositivi configurati (num_tipo > 0)
                    # NOTA: stat_value=0 è valido (sensore in stato normale/chiuso)
                    if num_tipo > 0:
                        parsed = parse_radio_stat(stat_value, num_tipo, num_spec)
                        parsed_stats[global_idx] = {
                            "nome": device_name,
                            "tipo": num_tipo,
                            "tipo_nome": get_device_type_name(num_tipo, num_spec),
                            "spec": num_spec,
                            "raw": stat_value,
                            "is_triggered": parsed.is_triggered(),
                            "stat": parsed.to_dict()
                        }
                        # Log solo se triggered o batteria scarica
                        if parsed.is_triggered() or parsed.batteria_scarica:
                            _LOGGER.info(
                                f"[{self.centrale_id}] Radio {global_idx} ({device_name}): "
                                f"raw=0x{stat_value:04X}, triggered={parsed.is_triggered()}, "
                                f"bat_low={parsed.batteria_scarica}"
                            )
                        else:
                            _LOGGER.debug(
                                f"[{self.centrale_id}] Radio {global_idx} ({device_name}): "
                                f"raw=0x{stat_value:04X}, OK"
                            )
                
                elif dev_type == "bus" and global_idx < len(pm_devices):
                    device_config = pm_devices[global_idx]
                    num_tipo = device_config.get("num_tipo_periferica", 0)
                    device_name = device_config.get("nome", f"Bus {global_idx}")
                    
                    if num_tipo > 0:
                        parsed = parse_bus_stat(stat_value, num_tipo)
                        parsed_stats[global_idx] = {
                            "nome": device_name,
                            "tipo": num_tipo,
                            "raw": stat_value,
                            "stat": parsed.to_dict()
                        }
                        _LOGGER.debug(f"[{self.centrale_id}] Bus {global_idx}: {parsed.to_dict()}")
                
                elif dev_type == "filari" and global_idx < len(pm_devices):
                    device_name = pm_devices[global_idx].get("nome", f"Filare {global_idx}")
                    parsed = parse_filare_stat(stat_value)
                    parsed_stats[global_idx] = {
                        "nome": device_name,
                        "raw": stat_value,
                        "is_triggered": parsed.is_triggered(),
                        "stat": parsed.to_dict()
                    }
                    _LOGGER.debug(f"[{self.centrale_id}] Filare {global_idx}: {parsed.to_dict()}")
            
            # Notifica callback per aggiornare le entità
            if self._dev_stats_callback and parsed_stats:
                await self._dev_stats_callback(self.centrale_id, dev_type, group, parsed_stats)
            
            # Callback generico
            if self.message_callback:
                await self.message_callback(
                    self.centrale_id,
                    {
                        "type": "gold_dev_stats",
                        "dev_type": dev_type,
                        "group": group,
                        "stats": stats,
                        "parsed": parsed_stats
                    }
                )
                
        except Exception as e:
            _LOGGER.error(f"[{self.centrale_id}] Error parsing Gold dev stats: {e}", exc_info=True)
        
        _LOGGER.debug(f"[{self.centrale_id}] ===================================")
        self._store_message("onGoldDevStats", data, timestamp)
    
    async def on_gold_sync(self, data):
        """Handler per progresso sincronizzazione Gold."""
        timestamp = datetime.now().isoformat()
        _LOGGER.debug(f"[{self.centrale_id}] Gold sync progress: {data}")
        
        self._store_message("onGoldSync", data, timestamp)
        
        if self.message_callback:
            await self.message_callback(
                self.centrale_id,
                {"type": "gold_sync", "data": data}
            )
    
    async def on_gold_end_sync(self, data):
        """Handler per fine sincronizzazione Gold - contiene physical map."""
        timestamp = datetime.now().isoformat()
        _LOGGER.info(f"[{self.centrale_id}] Gold sync completed, parsing physical map...")
        
        try:
            # Il dato arriva come stringa JSON
            if isinstance(data, str):
                pm_data = json.loads(data)
            else:
                pm_data = data
            
            # Estrai i dispositivi dalla physical map
            self._physical_map = {
                "radio": pm_data.get("radio", []),
                "bus": pm_data.get("bus", []),
                "filari": pm_data.get("filari", [])
            }
            
            _LOGGER.info(
                f"[{self.centrale_id}] Physical map loaded: "
                f"{len(self._physical_map['radio'])} radio, "
                f"{len(self._physical_map['bus'])} bus, "
                f"{len(self._physical_map['filari'])} filari"
            )
            
            # Log dispositivi radio configurati
            for idx, radio in enumerate(self._physical_map["radio"]):
                num_tipo = radio.get("num_tipo_periferica", 0)
                if num_tipo > 0:
                    nome = radio.get("nome", f"Radio {idx}")
                    tipo_nome = get_device_type_name(num_tipo, radio.get("num_spec_periferica", 0))
                    _LOGGER.debug(f"[{self.centrale_id}] Radio {idx}: {nome} ({tipo_nome})")
            
            if self.message_callback:
                await self.message_callback(
                    self.centrale_id,
                    {"type": "gold_end_sync", "physical_map": self._physical_map}
                )
                
        except Exception as e:
            _LOGGER.error(f"[{self.centrale_id}] Error parsing Gold physical map: {e}", exc_info=True)
        
        self._store_message("onGoldEndSync", data, timestamp)
    
    def set_physical_map(self, pm: Dict[str, Any]):
        """Imposta la physical map manualmente (es. da API login)."""
        self._physical_map = {
            "radio": pm.get("radio", []),
            "bus": pm.get("bus", []),
            "filari": pm.get("filari", [])
        }
        _LOGGER.info(
            f"[{self.centrale_id}] Physical map set: "
            f"{len(self._physical_map['radio'])} radio, "
            f"{len(self._physical_map['bus'])} bus, "
            f"{len(self._physical_map['filari'])} filari"
        )
    
    def set_dev_stats_callback(self, callback: Callable):
        """Imposta callback per aggiornamento device stats."""
        self._dev_stats_callback = callback
    
    def get_dev_stats(self, dev_type: str = None) -> Dict:
        """Ritorna gli ultimi device stats ricevuti."""
        if dev_type:
            return self._dev_stats.get(dev_type, {})
        return self._dev_stats
    
    def get_physical_map(self) -> Dict:
        """Ritorna la physical map."""
        return self._physical_map
    
    # ------------------------------ Utility methods ------------------------------
    
    def _store_message(self, event: str, data: Any, timestamp: str):
        """Store message for debugging."""
        message = {
            "timestamp": timestamp,
            "event": event,
            "data": data
        }
        
        self._last_messages.append(message)
        if len(self._last_messages) > self._max_messages:
            self._last_messages.pop(0)
    
    def get_last_messages(self, count: int = 10) -> list:
        """Get last N messages for debugging."""
        return self._last_messages[-count:]
    
    def get_discovered_events(self) -> dict:
        """Get all discovered events with counts."""
        return dict(self._gold_events)
