"""API client for Gold centrals."""
import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from ..common.api import CommonAPI
from .socket_client import GoldSocketClient
from .parser import GoldStateParser, GoldPhysicalMapParser
from .binary_sensor import update_gold_buscomm_binarysensors, update_gold_radio_sensors
from .sensor import update_gold_buscomm_sensors
from .const import API_GOLD_LOGIN_URL, API_GOLD_SEND_COMM_URL

_LOGGER = logging.getLogger(__name__)


class GoldAPI(CommonAPI):
    """API client specifically for Gold centrals."""
    
    def __init__(self, hass, email: str, password: str):
        """Initialize Gold API."""
        super().__init__(hass, email, password)
        self.brand = "lince-gold"
        
        # Gold specific parsers
        self._state_parser = GoldStateParser()
        self._physical_map_parser = GoldPhysicalMapParser()
        
        # Socket clients per centrale - IDENTICO A EUROPLUS
        self._socket_clients: Dict[int, GoldSocketClient] = {}
        
        # Cache stati
        self._states_cache: Dict[int, Dict] = {}
        self._physical_maps_cache: Dict[int, Dict] = {}
        
        _LOGGER.info("GoldAPI initialized")
    
    def is_socket_connected(self, row_id: int) -> bool:
        """Verifica se la socket è connessa per un sistema - IDENTICO A EUROPLUS."""
        # Per Gold, row_id corrisponde all'IdCentrale
        client = self._socket_clients.get(row_id)
        return client.is_connected() if client else False

    def get_socket_client(self, row_id: int) -> GoldSocketClient | None:
        """Restituisce il client socket - IDENTICO A EUROPLUS."""
        return self._socket_clients.get(row_id)

    async def start_socket_connection(self, row_id: int):
        """Avvia la connessione socket per un sistema - ADATTATO PER GOLD."""
        _LOGGER.debug(f"Avvio connessione socket Gold per centrale {row_id}")
        
        try:
            # Callback per connessione - IDENTICO A EUROPLUS
            async def connect_callback(cb_row_id: int):
                _LOGGER.info(f"[{cb_row_id}] Riconnesso alla socket Gold")

            # Callback per disconnessione - IDENTICO A EUROPLUS
            async def disconnect_callback(cb_row_id: int):
                _LOGGER.warning(f"[{cb_row_id}] Disconnessione dalla socket Gold rilevata")

            # Callback per messaggi - SPECIFICO PER GOLD
            async def message_callback(cb_row_id: int, message):
                _LOGGER.debug(f"[{cb_row_id}] Messaggio socket Gold ricevuto")
                
                # Usa i parser Gold per processare il messaggio
                await self._on_gold_message(cb_row_id, message)

            # Se il token è scaduto, login - IDENTICO A EUROPLUS
            if self.is_token_expired():
                _LOGGER.info("Token scaduto, provo login Gold")
                try:
                    await self.login(self._email, self._password)
                except Exception as e:
                    _LOGGER.warning("[socket %s] Login Gold fallita: %s", row_id, e)
                    return False

            # Se esiste già un client per questa centrale - IDENTICO A EUROPLUS
            if row_id in self._socket_clients:
                client = self._socket_clients[row_id]
                if client.is_connected():
                    _LOGGER.debug(f"Connessione socket Gold già avviata per {row_id}")
                    return True
                else:
                    _LOGGER.info(f"Rimuovo client socket Gold non connesso per {row_id}")
                    await client.stop()
                    self._socket_clients.pop(row_id, None)

            # Crea e avvia il nuovo client socket GOLD
            client = GoldSocketClient(
                token=self.token,
                centrale_id=row_id,
                message_callback=message_callback,
                disconnect_callback=disconnect_callback,
                connect_callback=connect_callback,
                hass=self.hass,
                api=self,
                email=self._email,
                password=self._password
            )

            connected = await client.start()
            if not connected:
                _LOGGER.info(f"[{row_id}] Connessione Gold in corso...")
                await asyncio.sleep(3)
                if not client.is_connected():
                    await client.stop()
                    return False

            self._socket_clients[row_id] = client
            _LOGGER.info(f"Socket Gold {row_id} avviata con successo")
            return True
            
        except Exception as e:
            _LOGGER.error(f"Errore avvio socket Gold {row_id}: {e}", exc_info=True)
            return False

    async def stop_socket_connection(self, row_id: int):
        """Ferma la connessione socket per un sistema - IDENTICO A EUROPLUS."""
        client = self._socket_clients.get(row_id)
        if client:
            try:
                await client.stop()
                _LOGGER.info(f"Socket Gold {row_id} fermata")
            except Exception as e:
                _LOGGER.error(f"Errore durante stop socket Gold {row_id}: {e}")
            finally:
                if row_id in self._socket_clients:
                    del self._socket_clients[row_id]
        
        # Pulisci cache stati
        self._states_cache.pop(row_id, None)
        _LOGGER.info(f"Socket Gold {row_id} completamente fermata")

    async def initialize_socket(self, centrale_id: int) -> bool:
        """Initialize Gold socket for a specific central - WRAPPER per compatibilità."""
        return await self.start_socket_connection(centrale_id)
    
    async def _on_gold_message(self, centrale_id: int, message: Any):
        """Handle Gold socket messages."""
        try:
            _LOGGER.debug(f"Gold message from {centrale_id}: type={message.get('type') if isinstance(message, dict) else 'unknown'}")
            
            # Parse based on message type
            if isinstance(message, dict):
                msg_type = message.get("type", "")
                
                if msg_type == "gold_state":
                    # Already parsed by socket client
                    parsed_state = message.get("data", {})
                    self._states_cache[centrale_id] = parsed_state
                    
                    # IMPORTANTE: Aggiorna i sensori con i dati parsati
                    # I dati sono già nella struttura corretta (stato, alim, prog, ecc.)
                    _LOGGER.debug(f"[{centrale_id}] Aggiornamento sensori Gold con dati parsati")
                    
                    # Aggiorna binary sensors
                    update_gold_buscomm_binarysensors(self, centrale_id, parsed_state)
                    
                    # Aggiorna sensors (voltage, current, firmware, etc.)
                    update_gold_buscomm_sensors(self, centrale_id, parsed_state)
                    
                    # Notify HA of state change
                    if self.hass:
                        self.hass.bus.async_fire(
                            "lince_gold_state_update",
                            {"centrale_id": centrale_id, "state": self._states_cache[centrale_id]}
                        )
                
                elif msg_type == "gold_dev_stats":
                    # Stato dispositivi (radio, bus, filari) via WebSocket
                    dev_type = message.get("dev_type", "")
                    group = message.get("group", 0)
                    parsed_stats = message.get("parsed", {})
                    
                    _LOGGER.debug(
                        f"[{centrale_id}] Gold dev stats: type={dev_type}, "
                        f"group={group}, devices={len(parsed_stats)}"
                    )
                    
                    # Aggiorna i sensori radio
                    if dev_type == "radio" and parsed_stats:
                        await update_gold_radio_sensors(centrale_id, dev_type, group, parsed_stats)
                    
                    # Notify HA
                    if self.hass:
                        self.hass.bus.async_fire(
                            "lince_gold_dev_stats_update",
                            {
                                "centrale_id": centrale_id,
                                "dev_type": dev_type,
                                "group": group,
                                "stats_count": len(parsed_stats)
                            }
                        )
                
                elif msg_type == "gold_end_sync":
                    # Physical map ricevuta - salva in cache
                    physical_map = message.get("physical_map", {})
                    self._physical_maps_cache[centrale_id] = physical_map
                    
                    _LOGGER.info(
                        f"[{centrale_id}] Physical map cached: "
                        f"{len(physical_map.get('radio', []))} radio, "
                        f"{len(physical_map.get('bus', []))} bus, "
                        f"{len(physical_map.get('filari', []))} filari"
                    )
                    
                    # Imposta la physical map nel socket client per il parsing
                    client = self._socket_clients.get(centrale_id)
                    if client:
                        client.set_physical_map(physical_map)
                    
                    # Notify HA
                    if self.hass:
                        self.hass.bus.async_fire(
                            "lince_gold_physical_map_update",
                            {"centrale_id": centrale_id}
                        )
                        
        except Exception as e:
            _LOGGER.error(f"Error handling Gold message: {e}", exc_info=True)
    
    async def _on_gold_connect(self, centrale_id: int):
        """Handle Gold socket connection."""
        _LOGGER.info(f"Gold socket connected for central {centrale_id}")
        
        # Request initial state
        # TODO: Discover how to request state
    
    async def _on_gold_disconnect(self, centrale_id: int):
        """Handle Gold socket disconnection."""
        _LOGGER.warning(f"Gold socket disconnected for central {centrale_id}")
    
    async def get_state(self, centrale_id: int) -> Optional[Dict]:
        """Get current state for a Gold central."""
        # Return from cache if available and recent
        if centrale_id in self._states_cache:
            return self._states_cache[centrale_id]
        
        # TODO: Implement HTTP fallback if socket not available
        return None
    
    def get_debug_info(self, centrale_id: int) -> Dict:
        """Get debug info for Gold central."""
        socket = self._socket_clients.get(centrale_id)
        if not socket:
            return {"error": "No socket client"}
        
        return {
            "connected": socket.is_connected(),
            "last_messages": socket.get_last_messages(20),
            "discovered_events": socket.get_discovered_events(),
            "cached_state": self._states_cache.get(centrale_id, {}),
            "parser_state": {
                "armed": self._state_parser.is_armed(),
                "problems": self._state_parser.get_system_problems(),
                "open_zones": self._state_parser.get_open_zones()
            }
        }
    
    async def gold_login_with_code(self, id_centrale: str, user_code: str) -> Optional[Dict]:
        """
        Esegue login Gold con codice utente per ottenere configurazione completa.
        
        POST /api/gold/login con payload {id_centrale, code}
        Restituisce: lm (logical map), pm (physical map) con nomi zone/dispositivi.
        
        Args:
            id_centrale: ID della centrale (stringa, es. "12345678")
            user_code: Codice utente (es. "123456")
            
        Returns:
            Dict con la risposta completa o None se fallisce
        """
        if self.is_token_expired():
            await self.login()
        
        headers = self.get_auth_header()
        payload = {
            "id_centrale": id_centrale,
            "code": user_code
        }
        
        try:
            _LOGGER.info(f"[Gold Login] Tentativo login con codice per centrale {id_centrale}")
            async with self.session.post(API_GOLD_LOGIN_URL, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    _LOGGER.warning("Token scaduto durante gold_login_with_code, ri-autenticando...")
                    await self.login()
                    headers = self.get_auth_header()
                    async with self.session.post(API_GOLD_LOGIN_URL, json=payload, headers=headers) as retry_resp:
                        if retry_resp.status != 200:
                            _LOGGER.error(f"Gold login con codice fallito: HTTP {retry_resp.status}")
                            return None
                        return await retry_resp.json()
                        
                elif resp.status != 200:
                    _LOGGER.error(f"Gold login con codice fallito: HTTP {resp.status}")
                    return None
                
                data = await resp.json()
                
                # LOG: Risposta completa per debug
                _LOGGER.info(f"[Gold Login] Risposta server: status={data.get('status')}, "
                            f"keys={list(data.keys())}")
                
                if data.get("status") != "OK":
                    # LOG: Mostra tutto il contenuto per capire il problema
                    _LOGGER.error(f"[Gold Login] FALLITO per centrale {id_centrale}:")
                    _LOGGER.error(f"  - status: {data.get('status')}")
                    _LOGGER.error(f"  - message: {data.get('message', 'nessun messaggio')}")
                    _LOGGER.error(f"  - risposta completa: {data}")
                    return None
                
                # LOG: Contenuto physical map
                pm = data.get("pm", {})
                _LOGGER.info(f"[Gold Login] SUCCESSO! Physical map: "
                            f"radio={len(pm.get('radio', []))}, "
                            f"bus={len(pm.get('bus', []))}, "
                            f"filari={len(pm.get('filari', []))}")
                
                return data
                
        except Exception as e:
            _LOGGER.error(f"Errore durante gold_login_with_code: {e}", exc_info=True)
            return None
    
    def parse_zone_names_from_login(self, login_data: Dict) -> Dict[str, Dict[int, str]]:
        """
        Estrae i nomi delle zone dalla risposta di gold_login_with_code.
        
        Args:
            login_data: Risposta da gold_login_with_code
            
        Returns:
            Dict con chiavi 'filari', 'radio', 'bus' contenenti {indice: nome}
        """
        result = {
            "filari": {},
            "radio": {},
            "bus": {},
            "zone": {},  # Zone logiche
        }
        
        try:
            pm = login_data.get("pm", {})
            lm = login_data.get("lm", {})
            
            # Parse filari: array di [config_hex, nome]
            filari = pm.get("filari", [])
            for idx, entry in enumerate(filari):
                if isinstance(entry, list) and len(entry) >= 2:
                    name = entry[1].strip() if entry[1] else f"Filare {idx + 1}"
                    # Salta nomi default "INGR. FILARE  X "
                    if not name.startswith("INGR. FILARE"):
                        result["filari"][idx] = name
                    else:
                        result["filari"][idx] = name.strip()
            
            # Parse radio: array di [config_hex, nome]
            radio = pm.get("radio", [])
            for idx, entry in enumerate(radio):
                if isinstance(entry, list) and len(entry) >= 2:
                    config_hex = entry[0] if entry[0] else ""
                    name = entry[1].strip() if entry[1] else f"Radio {idx + 1}"
                    
                    # Salta dispositivi non configurati (pattern default)
                    if config_hex.startswith("000700000000ffffff"):
                        continue  # Dispositivo non configurato
                    
                    # Salta nomi default "DISP. RADIO  X "
                    if name.startswith("DISP. RADIO"):
                        continue
                    
                    result["radio"][idx] = name.strip()
            
            # Parse bus: array di [config_hex, nome]
            bus = pm.get("bus", [])
            for idx, entry in enumerate(bus):
                if isinstance(entry, list) and len(entry) >= 2:
                    config_hex = entry[0] if entry[0] else ""
                    name = entry[1].strip() if entry[1] else f"Bus {idx + 1}"
                    
                    # Salta dispositivi non configurati
                    if config_hex == "ffffff00":
                        continue
                    
                    # Salta nomi default "DISP. BUS    X "
                    if name.startswith("DISP. BUS"):
                        continue
                    
                    result["bus"][idx] = name.strip()
            
            # Parse zone logiche da lm
            zone_list = lm.get("zone", [])
            for idx, zone in enumerate(zone_list):
                if isinstance(zone, dict):
                    name = zone.get("nome", f"Zona {idx + 1}").strip()
                    result["zone"][idx] = name
            
            _LOGGER.debug(f"Parsed zone names: filari={len(result['filari'])}, "
                         f"radio={len(result['radio'])}, bus={len(result['bus'])}, "
                         f"zone={len(result['zone'])}")
            
        except Exception as e:
            _LOGGER.error(f"Errore parsing nomi zone: {e}", exc_info=True)
        
        return result
    
    async def gold_send_comm(self, id_centrale: str, prog: int) -> bool:
        """
        Invia comando di attivazione/disattivazione alla centrale Gold.
        
        POST /api/gold/send_comm con payload {id_centrale, prog}
        
        Args:
            id_centrale: ID della centrale (stringa)
            prog: Maschera programmi da attivare:
                  - 0 = disarm (tutti i programmi spenti)
                  - 1 = G1
                  - 2 = G2
                  - 3 = G1 + G2
                  - 4 = G3
                  - 5 = G1 + G3
                  - 6 = G2 + G3
                  - 7 = G1 + G2 + G3
                  
        Returns:
            True se il comando è stato inviato con successo
            
        Note:
            IMPORTANTE: Prima di chiamare send_comm, devi aver chiamato
            gold_login_with_code() per autenticare l'utente.
        """
        if self.is_token_expired():
            await self.login()
        
        headers = self.get_auth_header()
        payload = {
            "id_centrale": id_centrale,
            "prog": prog
        }
        
        try:
            _LOGGER.debug(f"Gold send_comm per centrale {id_centrale}, prog={prog}")
            async with self.session.post(API_GOLD_SEND_COMM_URL, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    _LOGGER.warning("Token scaduto durante gold_send_comm, ri-autenticando...")
                    await self.login()
                    headers = self.get_auth_header()
                    async with self.session.post(API_GOLD_SEND_COMM_URL, json=payload, headers=headers) as retry_resp:
                        if retry_resp.status != 200:
                            _LOGGER.error(f"Gold send_comm fallito: HTTP {retry_resp.status}")
                            return False
                        _LOGGER.info(f"Gold send_comm riuscito per centrale {id_centrale}, prog={prog}")
                        return True
                        
                elif resp.status != 200:
                    _LOGGER.error(f"Gold send_comm fallito: HTTP {resp.status}")
                    return False
                
                _LOGGER.info(f"Gold send_comm riuscito per centrale {id_centrale}, prog={prog}")
                return True
                
        except Exception as e:
            _LOGGER.error(f"Errore durante gold_send_comm: {e}", exc_info=True)
            return False
    
    async def gold_arm_disarm(self, id_centrale: str, user_code: str, prog: int, delay_ms: int = 250) -> bool:
        """
        Esegue il flusso completo di arm/disarm per Gold:
        1. Login con codice utente
        2. Attesa breve (per sicurezza)
        3. Invio comando send_comm
        
        Args:
            id_centrale: ID della centrale
            user_code: Codice utente per autenticazione
            prog: Maschera programmi (0 = disarm, 1-7 = combinazioni G1/G2/G3)
            delay_ms: Ritardo tra login e send_comm (default 250ms)
            
        Returns:
            True se l'operazione è completata con successo
        """
        try:
            # 1. Login con codice utente
            _LOGGER.debug(f"Gold arm/disarm: login per centrale {id_centrale}")
            login_result = await self.gold_login_with_code(id_centrale, user_code)
            
            if not login_result or login_result.get("status") != "OK":
                _LOGGER.error(f"Gold arm/disarm: login fallito per centrale {id_centrale}")
                return False
            
            # 2. Attesa breve
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            
            # 3. Invio comando
            _LOGGER.debug(f"Gold arm/disarm: send_comm prog={prog}")
            success = await self.gold_send_comm(id_centrale, prog)
            
            if success:
                action = "disarm" if prog == 0 else f"arm (prog={prog})"
                _LOGGER.info(f"Gold {action} completato per centrale {id_centrale}")
            
            return success
            
        except Exception as e:
            _LOGGER.error(f"Errore durante gold_arm_disarm: {e}", exc_info=True)
            return False
    
    def get_physical_map(self, centrale_id: int) -> Optional[Dict]:
        """
        Restituisce la physical map dalla cache.
        
        Args:
            centrale_id: ID della centrale
            
        Returns:
            Dict con chiavi 'radio', 'bus', 'filari' o None se non disponibile
        """
        return self._physical_maps_cache.get(centrale_id)
    
    def set_physical_map(self, centrale_id: int, physical_map: Dict):
        """
        Imposta la physical map nella cache e nel socket client.
        
        Args:
            centrale_id: ID della centrale
            physical_map: Dict con chiavi 'radio', 'bus', 'filari'
        """
        self._physical_maps_cache[centrale_id] = physical_map
        
        # LOG: Mostra chiavi disponibili per debug
        _LOGGER.debug(f"[set_physical_map] centrale_id={centrale_id}, socket_clients keys={list(self._socket_clients.keys())}")
        
        # Imposta anche nel socket client per il parsing in tempo reale
        # Prova sia con centrale_id che con le chiavi esistenti
        client = self._socket_clients.get(centrale_id)
        
        # Se non trovato, prova conversione stringa/int
        if not client:
            client = self._socket_clients.get(str(centrale_id))
        if not client:
            try:
                client = self._socket_clients.get(int(centrale_id))
            except (ValueError, TypeError):
                pass
        
        # Se ancora non trovato, cerca tra tutte le chiavi una che contenga centrale_id
        if not client:
            for key in self._socket_clients.keys():
                if str(centrale_id) in str(key) or str(key) in str(centrale_id):
                    client = self._socket_clients.get(key)
                    _LOGGER.info(f"[set_physical_map] Trovato socket con chiave {key} per centrale {centrale_id}")
                    break
        
        if client:
            client.set_physical_map(physical_map)
            _LOGGER.info(
                f"[{centrale_id}] Physical map set nel socket: "
                f"{len(physical_map.get('radio', []))} radio, "
                f"{len(physical_map.get('bus', []))} bus, "
                f"{len(physical_map.get('filari', []))} filari"
            )
        else:
            _LOGGER.warning(
                f"[{centrale_id}] Socket client NON trovato! "
                f"Physical map salvata solo in cache. "
                f"Socket disponibili: {list(self._socket_clients.keys())}"
            )
    
    async def fetch_and_cache_physical_map(self, id_centrale: str, user_code: str, row_id: int | None = None) -> Optional[Dict]:
        """
        Recupera la physical map tramite login Gold e la salva in cache.
        
        Args:
            id_centrale: ID della centrale (stringa)
            user_code: Codice utente per autenticazione
            
        Returns:
            Dict con la physical map parsata o None se fallisce
        """
        try:
            login_data = await self.gold_login_with_code(id_centrale, user_code)
            
            if not login_data or login_data.get("status") != "OK":
                _LOGGER.error(f"Impossibile recuperare physical map per {id_centrale}")
                return None
            
            pm = login_data.get("pm", {})
            
            # Parsa la physical map nel formato usato internamente
            physical_map = self._parse_physical_map_from_login(pm)
            
            # Salva in cache con la stessa chiave usata dal socket client (row_id),
            # altrimenti la physical map non viene agganciata al socket giusto.
            cache_key = row_id
            if cache_key is None:
                try:
                    cache_key = int(id_centrale)
                except ValueError:
                    cache_key = id_centrale

            self.set_physical_map(cache_key, physical_map)
            
            return physical_map
            
        except Exception as e:
            _LOGGER.error(f"Errore durante fetch_and_cache_physical_map: {e}", exc_info=True)
            return None
    
    def _parse_physical_map_from_login(self, pm: Dict) -> Dict:
        """
        Converte la physical map dal formato login al formato interno.
        
        Il formato login ha array di [config_hex, nome].
        Il formato interno ha dict con campi parsati.
        """
        from .parser.physical_map import GoldPhysicalMapParser
        
        result = {
            "radio": [],
            "bus": [],
            "filari": []
        }
        
        try:
            # LOG: Contenuto raw della pm
            _LOGGER.info(f"[PM Parse] Parsing physical_map dal login:")
            _LOGGER.info(f"  - radio entries: {len(pm.get('radio', []))}")
            _LOGGER.info(f"  - bus entries: {len(pm.get('bus', []))}")
            _LOGGER.info(f"  - filari entries: {len(pm.get('filari', []))}")
            
            # Parse radio
            for idx, entry in enumerate(pm.get("radio", [])):
                if isinstance(entry, list) and len(entry) >= 2:
                    config_hex = entry[0] if entry[0] else ""
                    name = entry[1].strip() if entry[1] else f"Radio {idx}"
                    
                    # LOG: Mostra ogni entry raw (solo prime 3)
                    if idx < 3:
                        _LOGGER.info(f"  Radio[{idx}] raw: hex_len={len(config_hex)}, name='{name}'")
                    
                    # Parsa la configurazione hex per estrarre tipo periferica
                    parsed = GoldPhysicalMapParser.parse_radio_config(config_hex)
                    parsed["nome"] = name
                    parsed["index"] = idx
                    
                    # LOG: Risultato parsing (solo prime 3)
                    if idx < 3:
                        _LOGGER.info(f"  Radio[{idx}] parsed: tipo={parsed.get('num_tipo_periferica', 'N/A')}, "
                                    f"spec={parsed.get('num_spec_periferica', 'N/A')}")
                    
                    result["radio"].append(parsed)
                else:
                    _LOGGER.warning(f"  Radio[{idx}]: formato non valido: {type(entry)}")
                    result["radio"].append({
                        "index": idx,
                        "nome": f"Radio {idx}",
                        "num_tipo_periferica": 0,
                        "num_spec_periferica": 0
                    })
            
            # Parse bus
            for idx, entry in enumerate(pm.get("bus", [])):
                if isinstance(entry, list) and len(entry) >= 2:
                    config_hex = entry[0] if entry[0] else ""
                    name = entry[1].strip() if entry[1] else f"Bus {idx}"
                    
                    parsed = GoldPhysicalMapParser.parse_bus_config(config_hex)
                    parsed["nome"] = name
                    parsed["index"] = idx
                    result["bus"].append(parsed)
                else:
                    result["bus"].append({
                        "index": idx,
                        "nome": f"Bus {idx}",
                        "num_tipo_periferica": 0
                    })
            
            # Parse filari
            for idx, entry in enumerate(pm.get("filari", [])):
                if isinstance(entry, list) and len(entry) >= 2:
                    name = entry[1].strip() if entry[1] else f"Filare {idx}"
                    result["filari"].append({
                        "index": idx,
                        "nome": name
                    })
                else:
                    result["filari"].append({
                        "index": idx,
                        "nome": f"Filare {idx}"
                    })
            
        except Exception as e:
            _LOGGER.error(f"Errore parsing physical map: {e}", exc_info=True)
        
        return result
    