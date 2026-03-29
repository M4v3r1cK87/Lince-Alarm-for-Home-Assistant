"""
EuroPlus/EuroNET Local Client per Home Assistant.

Questo modulo fornisce l'interfaccia locale per comunicare con le centrali
Lince EuroPlus/EuroNET tramite HTTP, bypassando il cloud.

"""

import base64
import re
import time
import logging
import threading
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

_LOGGER = logging.getLogger(__name__)


# ============================================================================
# COSTANTI
# ============================================================================

class TipoIngresso(Enum):
    """Tipo di ingresso filare."""
    NC = 0
    BILANCIATO = 1
    DOPPIO_BILANCIATO = 2


class Logica(Enum):
    """Logica ingresso."""
    AND = 0
    OR = 1


class TempoTrigger(Enum):
    """Tempo di trigger."""
    MS_300 = 0
    MS_600 = 1


# ============================================================================
# DATACLASS
# ============================================================================

@dataclass
class StatoCentrale:
    """Stato completo della centrale."""
    # Data/ora
    datetime: str = ""
    timestamp: str = ""
    
    # Programmi
    g1: bool = False
    g2: bool = False
    g3: bool = False
    gext: bool = False
    
    # Stato generale
    stato: str = ""  # K=OK, O=ZoneOpen, F=Fault, S=Servizio
    modo_servizio: bool = False
    logout: bool = False
    
    # Alimentazione
    rete_220v: bool = True
    batteria_interna_ok: bool = True
    batteria_esterna_ok: bool = True
    fusibile_uscite_ok: bool = True
    
    # Allarmi
    allarme: bool = False
    guasto: bool = False
    
    # Sabotaggi
    sabotaggio_centrale: bool = False
    sabotaggio_allarme_ingresso: bool = False
    sabotaggio_ingressi: bool = False
    sabotaggio_dispositivi_bus: bool = False
    allarme_integrita_bus: bool = False
    
    # Memorie sabotaggi
    memoria_sabotaggio_centrale: bool = False
    memoria_sabotaggio_allarme_ingresso: bool = False
    memoria_sabotaggio_ingressi: bool = False
    memoria_sabotaggio_dispositivi_bus: bool = False
    memoria_integrita_bus: bool = False
    
    # Ingressi globali
    ingressi_aperti: bool = False
    ingressi_esclusi: bool = False
    
    # Espansioni
    espansione_1: bool = False
    espansione_2: bool = False
    espansione_3: bool = False
    espansione_4: bool = False
    espansione_5: bool = False
    espansione_radio: bool = False
    conflitto_espansione_radio: bool = False
    
    # Valori
    tensione_batteria: float = 0.0
    tensione_bus: float = 0.0
    temperatura: float = 0.0
    release_sw: float = 0.0
    
    # Raw
    gstate: str = ""
    raw_in_state: str = ""


@dataclass
class StatoZonaFilare:
    """Stato di una zona filare."""
    numero: int = 0
    allarme_24h: bool = False
    aperta: bool = False
    esclusa: bool = False
    memoria_24h: bool = False
    memoria_allarme: bool = False


@dataclass
class StatoZonaRadio:
    """Stato di una zona radio."""
    numero: int = 0
    allarme_24h: bool = False
    memoria_24h: bool = False
    aperta: bool = False
    memoria_allarme: bool = False
    supervisione: bool = False
    batteria_scarica: bool = False


@dataclass
class ConfigZonaFilare:
    """Configurazione di una zona filare."""
    numero: int = 0
    nome: str = ""
    
    # Programmi associati
    g1: bool = False
    g2: bool = False
    g3: bool = False
    gext: bool = False
    
    # Tipo e logica
    tipo_ingresso: TipoIngresso = TipoIngresso.NC
    tempo_trigger: TempoTrigger = TempoTrigger.MS_300
    logica: Logica = Logica.AND
    numero_allarmi: int = 0  # 0 = infiniti
    
    # Flags
    escluso: bool = False
    silenzioso: bool = False
    test: bool = False
    parzializzabile: bool = False
    ronda: bool = False
    h24: bool = False
    ritardato: bool = False
    percorso: bool = False
    
    # Tempi (in secondi)
    tempo_ingresso_min: int = 0
    tempo_ingresso_sec: int = 0
    tempo_uscita_min: int = 0
    tempo_uscita_sec: int = 0
    
    # Uscite associate
    uscita_allarme1: bool = False
    uscita_allarme2: bool = False
    uscita_fuoco: bool = False
    uscita_campanello: bool = False
    uscita_elettroserratura: bool = False


@dataclass
class ConfigZonaRadio:
    """Configurazione di una zona radio."""
    numero: int = 0
    nome: str = ""
    supervisionato: bool = False
    escluso: bool = False
    
    # Associazioni a ingressi filari
    associazione_1: bool = False  # 26/31
    associazione_2: bool = False  # 27/32
    associazione_3: bool = False  # 28/33
    associazione_4: bool = False  # 29/34
    associazione_5: bool = False  # 30/35


@dataclass
class ConfigTempi:
    """Configurazione tempi centrale."""
    allarme_min: int = 0
    allarme_sec: int = 30
    fuoco_min: int = 1
    fuoco_sec: int = 30
    silenzioso_sec: int = 6
    silenzioso_dec: int = 0
    campanello_sec: int = 6
    campanello_dec: int = 0
    elettroserratura_sec: int = 2
    elettroserratura_dec: int = 0
    ronda_min: int = 10
    ronda_sec: int = 0


# ============================================================================
# HTML PARSER PER CONFIGURAZIONI
# ============================================================================

class ZonaFilareParser:
    """Parser HTML per configurazione zona filare usando regex."""
    
    def __init__(self):
        self.config = ConfigZonaFilare()
        
    def parse(self, html: str):
        """Parsa HTML della pagina configurazione zona filare."""
        
        # Estrai nome da input text
        nome_match = re.search(r'<input[^>]*name="nom_i"[^>]*value="([^"]*)"', html)
        if nome_match:
            self.config.nome = nome_match.group(1).strip()
            
        # Estrai tutti i checkbox con stato
        checkbox_mapping = {
            "G1_i": "g1",
            "G2_i": "g2", 
            "G3_i": "g3",
            "Ge_i": "gext",
            "esc_i": "escluso",
            "sil_i": "silenzioso",
            "tes_i": "test",
            "par_i": "parzializzabile",
            "ron_i": "ronda",
            "h24_i": "h24",
            "rit_i": "ritardato",
            "per_i": "percorso",
            "A_i": "uscita_allarme1",
            "K_i": "uscita_allarme2",
            "F_i": "uscita_fuoco",
            "C_i": "uscita_campanello",
            "E_i": "uscita_elettroserratura",
        }
        
        for cb_match in re.finditer(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"([^>]*)>', html):
            name = cb_match.group(1)
            rest = cb_match.group(0)
            checked = 'checked' in rest.lower()
            if name in checkbox_mapping:
                setattr(self.config, checkbox_mapping[name], checked)
                
        # Estrai select con valore selezionato
        select_mapping = {
            "tipo": ("tipo_ingresso", lambda v: TipoIngresso(v) if 0 <= v <= 2 else TipoIngresso.NC),
            "Trig": ("tempo_trigger", lambda v: TempoTrigger(v) if 0 <= v <= 1 else TempoTrigger.MS_300),
            "Log": ("logica", lambda v: Logica(v) if 0 <= v <= 1 else Logica.AND),
            "NMA": ("numero_allarmi", lambda v: v),
            "t_inM": ("tempo_ingresso_min", lambda v: v),
            "t_inS": ("tempo_ingresso_sec", lambda v: v),
            "t_ouM": ("tempo_uscita_min", lambda v: v),
            "t_ouS": ("tempo_uscita_sec", lambda v: v),
        }
        
        for select_match in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', html, re.DOTALL | re.IGNORECASE):
            select_name = select_match.group(1)
            options_html = select_match.group(2)
            
            # Trova opzione selezionata
            selected_match = re.search(r'<option[^>]*value="(\d+)"[^>]*selected[^>]*>', options_html, re.IGNORECASE)
            if selected_match and select_name in select_mapping:
                try:
                    val = int(selected_match.group(1))
                    attr_name, converter = select_mapping[select_name]
                    setattr(self.config, attr_name, converter(val))
                except (ValueError, KeyError):
                    pass
                    
        return self.config


class ZonaRadioParser:
    """Parser HTML per configurazione zona radio usando regex."""
    
    def __init__(self):
        self.config = ConfigZonaRadio()
        
    def parse(self, html: str):
        """Parsa HTML della pagina configurazione zona radio."""
        
        # Estrai nome da input text
        nome_match = re.search(r'<input[^>]*name="nom_r"[^>]*value="([^"]*)"', html)
        if nome_match:
            self.config.nome = nome_match.group(1).strip()
            
        # Estrai tutti i checkbox con stato
        checkbox_mapping = {
            "sup_r": "supervisionato",
            "esc_r": "escluso",
            "a1_r": "associazione_1",
            "a2_r": "associazione_2",
            "a3_r": "associazione_3",
            "a4_r": "associazione_4",
            "a5_r": "associazione_5",
        }
        
        for cb_match in re.finditer(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"([^>]*)>', html):
            name = cb_match.group(1)
            rest = cb_match.group(0)
            checked = 'checked' in rest.lower()
            if name in checkbox_mapping:
                setattr(self.config, checkbox_mapping[name], checked)
                
        return self.config


class TempiParser:
    """Parser HTML per configurazione tempi usando regex."""
    
    def __init__(self):
        self.config = ConfigTempi()
        
    def parse(self, html: str):
        """Parsa HTML della pagina configurazione tempi."""
        
        select_mapping = {
            "alM": "allarme_min",
            "alS": "allarme_sec",
            "fuM": "fuoco_min",
            "fuS": "fuoco_sec",
            "siS": "silenzioso_sec",
            "siD": "silenzioso_dec",
            "caS": "campanello_sec",
            "caD": "campanello_dec",
            "elS": "elettroserratura_sec",
            "elD": "elettroserratura_dec",
            "roM": "ronda_min",
            "roS": "ronda_sec",
        }
        
        for select_match in re.finditer(r'<select[^>]*(?:name|id)="([^"]+)"[^>]*>(.*?)</select>', html, re.DOTALL | re.IGNORECASE):
            select_name = select_match.group(1)
            options_html = select_match.group(2)
            
            # Trova opzione selezionata
            selected_match = re.search(r'<option[^>]*value="(\d+)"[^>]*selected[^>]*>', options_html, re.IGNORECASE)
            if selected_match and select_name in select_mapping:
                try:
                    val = int(selected_match.group(1))
                    attr_name = select_mapping[select_name]
                    setattr(self.config, attr_name, val)
                except ValueError:
                    pass
                    
        return self.config


# ============================================================================
# CLIENT PRINCIPALE
# ============================================================================

class EuroNetClient:
    """
    Client locale per centrali Lince EuroPlus/EuroNET.
    
    Permette di:
    - Leggere stato centrale
    - Armare/disarmare programmi
    - Leggere stato zone filari e radio
    - Leggere configurazioni zone e tempi (HTML scraping)
    """
    
    # Endpoints
    ENDPOINTS = {
        "status": "status.xml",
        "login": "login.html",
        "logout": "logout.html",
        "index": "index.htm",
        "reboot": "protect/reboot.cgi",
        "zone_filari_config": "ingresso-filari.html",
        "zone_radio_config": "ingresso-radio.html",
        "tempi_config": "tempi.html",
    }
    
    # POST data
    POST_DATA = {
        "stato_impianto": "Sta=",
        "ingressi_filari": "Ing=0",
        "ingressi_radio": "Ing=1",
        "base": "nul=",
    }
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 80,
        timeout: int = 10
    ):
        """
        Inizializza il client.
        
        Args:
            host: IP o hostname della centrale
            username: Username HTTP Basic Auth
            password: Password HTTP Basic Auth
            port: Porta HTTP (default 80)
            timeout: Timeout richieste in secondi
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        
        # Costruisci base_url con porta
        if port == 80:
            self.base_url = f"http://{host}"
        else:
            self.base_url = f"http://{host}:{port}"
        
        # Crea sessione con auth
        self.session = requests.Session()
        credentials = f"{username}:{password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self.session.headers.update({
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded"
        })
        
        # Lock per serializzare le richieste HTTP
        # La centrale non gestisce bene richieste concorrenti
        self._request_lock = threading.Lock()
        
        # Contatore redirect consecutivi per auto-recovery sessione
        # Quando raggiunge la soglia, viene eseguito un force-reset della sessione
        self._consecutive_redirect_failures = 0
        self._REDIRECT_RESET_THRESHOLD = 3
        
    # ========================================================================
    # METODI PRIVATI
    # ========================================================================
    
    def _force_session_reset_raw(self) -> None:
        """
        Forza il reset della sessione web della centrale.
        
        Chiama POST NoLogin.html con Login=force per disconnettere qualsiasi
        utente attualmente connesso (inclusa la sessione scaduta di HA stessa).
        
        ATTENZIONE: non usa _request_lock né _post/_get perché viene chiamato
        dall'interno di _get/_post mentre il lock è già acquisito.
        """
        try:
            reset_url = f"{self.base_url}/NoLogin.html"
            _LOGGER.warning(
                "Troppi redirect consecutivi (%d), forzo reset sessione HTTP "
                "(POST NoLogin.html Login=force)",
                self._consecutive_redirect_failures
            )
            self.session.post(
                reset_url,
                data="Login=force",
                timeout=self.timeout,
                allow_redirects=False
            )
            # Attesa per permettere alla centrale di completare il reset
            time.sleep(1.2)
        except Exception as e:
            _LOGGER.debug("Errore durante force session reset: %s", e)

    def _post(self, endpoint: str, data: str) -> Optional[str]:
        """Esegue POST request con lock per serializzare le richieste."""
        url = f"{self.base_url}/{endpoint}"
        
        # Usa il lock per evitare richieste parallele alla centrale
        with self._request_lock:
            try:
                response = self.session.post(url, data=data, timeout=self.timeout)
                if response.status_code == 200:
                    # Verifica se dopo i redirect siamo finiti su NoLogin (sessione scaduta)
                    if "NoLogin" in response.url or "NoLogin" in response.text[:500]:
                        _LOGGER.debug(f"Sessione scaduta su {endpoint} - redirect a NoLogin")
                        return None
                    # Successo: reset contatore redirect
                    self._consecutive_redirect_failures = 0
                    return response.text
                # HTTP non-200: logga come debug se è un redirect, error altrimenti
                if response.status_code in (301, 302, 303, 307, 308):
                    self._consecutive_redirect_failures += 1
                    _LOGGER.debug(f"HTTP {response.status_code} redirect su {endpoint} -> {response.url}")
                    if self._consecutive_redirect_failures >= self._REDIRECT_RESET_THRESHOLD:
                        self._force_session_reset_raw()
                        self._consecutive_redirect_failures = 0
                else:
                    _LOGGER.warning(f"HTTP {response.status_code} su {endpoint}. Response: {response.text[:200]}")
                return None
            except requests.exceptions.RequestException as e:
                _LOGGER.debug(f"Errore connessione POST {endpoint}: {e}")
                return None
            
    def _get(self, endpoint: str, params: str = "") -> Optional[str]:
        """Esegue GET request con lock per serializzare le richieste."""
        url = f"{self.base_url}/{endpoint}"
        if params:
            url = f"{url}?{params}"
        
        # Usa il lock per evitare richieste parallele alla centrale
        with self._request_lock:
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 200:
                    # Verifica se dopo i redirect siamo finiti su NoLogin (sessione scaduta)
                    if "NoLogin" in response.url or "NoLogin" in response.text[:500]:
                        _LOGGER.debug(f"Sessione scaduta su {endpoint} - redirect a NoLogin")
                        return None
                    # Successo: reset contatore redirect
                    self._consecutive_redirect_failures = 0
                    return response.text
                # HTTP non-200: logga come debug se è un redirect, error altrimenti
                if response.status_code in (301, 302, 303, 307, 308):
                    self._consecutive_redirect_failures += 1
                    _LOGGER.debug(f"HTTP {response.status_code} redirect su {endpoint} -> {response.url}")
                    if self._consecutive_redirect_failures >= self._REDIRECT_RESET_THRESHOLD:
                        self._force_session_reset_raw()
                        self._consecutive_redirect_failures = 0
                else:
                    _LOGGER.warning(f"HTTP {response.status_code} su {endpoint}. Response: {response.text[:200]}")
                return None
            except requests.exceptions.RequestException as e:
                _LOGGER.debug(f"Errore connessione GET {endpoint}: {e}")
                return None
            
    def _parse_xml(self, xml_content: str) -> Optional[Dict[str, str]]:
        """Parsa risposta XML base."""
        try:
            root = ET.fromstring(xml_content)
            return {
                "dtime": root.findtext("dtime", ""),
                "gstate": root.findtext("gstate", ""),
                "in_state": root.findtext("in_state", ""),
                "aview": root.findtext("aview", ""),
            }
        except ET.ParseError as e:
            _LOGGER.error(f"Errore parsing XML: {e}")
            return None
            
    def _get_dynamic_keys(self, max_retries: int = 3) -> Optional[List[int]]:
        """
        Estrae le chiavi XOR dinamiche da index.htm.
        
        Le chiavi cambiano ad ogni richiesta e sono necessarie per cifrare
        il codice di login. Implementa retry automatico in caso di risposta
        incompleta dalla centrale.
        
        Args:
            max_retries: Numero massimo di tentativi
        
        Returns:
            Lista di 16 interi per XOR encoding, o None se errore
        """
        for attempt in range(max_retries):
            html = self._get(self.ENDPOINTS["index"])
            if not html:
                if attempt < max_retries - 1:
                    time.sleep(0.3)
                continue
                
            match = re.search(r'arr\s*=\s*"([\d,]+)"', html)
            if not match:
                # Log del contenuto per debug
                _LOGGER.warning(
                    "Chiavi XOR non trovate in index.htm (tentativo %d/%d). "
                    "Contenuto (primi 500 char): %s",
                    attempt + 1, max_retries, html[:500] if html else "VUOTO"
                )
                if attempt < max_retries - 1:
                    time.sleep(0.3)
                continue
                
            keys_str = match.group(1)
            keys = [int(k) for k in keys_str.strip(',').split(',') if k]
            
            if len(keys) >= 16:
                return keys[:16]
            
            # Chiavi insufficienti - riprova
            _LOGGER.debug("Chiavi XOR insufficienti: %d (serve 16)", len(keys))
            if attempt < max_retries - 1:
                time.sleep(0.3)
        
        _LOGGER.error("Impossibile ottenere chiavi XOR dopo %d tentativi", max_retries)
        return None
        
    def _encode_password(self, code: str, keys: List[int]) -> str:
        """
        Cifra il codice per EuroNET usando XOR.
        
        Args:
            code: Codice numerico (max 6 cifre)
            keys: Chiavi XOR
            
        Returns:
            Stringa cifrata di 18 caratteri
        """
        result = ""
        for i in range(6):
            if i < len(code):
                char_code = ord(code[i])
            else:
                char_code = 245 + i
            xored = char_code ^ keys[i]
            result += str(xored).zfill(3)
        return result
        
    # ========================================================================
    # AUTENTICAZIONE
    # ========================================================================
    
    def login(self, code: str) -> bool:
        """
        Effettua login con codice allarme.
        
        Args:
            code: Codice numerico (max 6 cifre)
            
        Returns:
            True se login riuscito
        """
        keys = self._get_dynamic_keys()
        if not keys:
            _LOGGER.error("Login fallito: impossibile ottenere chiavi XOR")
            return False
            
        encoded = self._encode_password(code, keys)
        response = self._post(self.ENDPOINTS["login"], f"psw={encoded}")
        
        if response:
            # Verifica se siamo loggati
            status = self.get_stato_centrale()
            if status and not status.logout:
                _LOGGER.debug("Login riuscito")
                return True
            else:
                _LOGGER.error(
                    "Login fallito: POST OK ma stato non valido. "
                    "status=%s, logout=%s",
                    status is not None, status.logout if status else "N/A"
                )
        else:
            _LOGGER.error(
                "Login fallito: POST login ritorna None (possibile redirect o errore HTTP)"
            )
        return False
        
    def logout(self, force: bool = True) -> bool:
        """
        Effettua logout.
        
        Args:
            force: Se True, forza il logout anche di altri utenti
            
        Returns:
            True se logout riuscito
        """
        try:
            if force:
                # Force logout - disconnette qualsiasi utente collegato
                self._post("NoLogin.html", "Login=force")
            
            # Logout normale
            response = self._post(self.ENDPOINTS["logout"], "logout=1")
            return response is not None
        except Exception as e:
            _LOGGER.debug("Logout error (ignored): %s", e)
            return False
        
    # ========================================================================
    # ARMA/DISARMA
    # ========================================================================
    
    def arm(self, code: str, programmi: List[str]) -> bool:
        """
        Arma programmi specifici.
        
        Args:
            code: Codice allarme
            programmi: Lista programmi ["G1", "G2", "G3", "GExt"]
            
        Returns:
            True se comando inviato con successo
        """
        # Login prima
        if not self.login(code):
            return False
        
        # Attesa più lunga per permettere alla centrale di elaborare il login
        time.sleep(1.5)
        
        # Costruisci query string
        params = []
        for prog in programmi:
            prog_upper = prog.upper()
            if prog_upper in ["G1", "G2", "G3", "GEXT"]:
                params.append(f"{prog_upper}=on")
                
        if not params:
            _LOGGER.error("Nessun programma valido specificato")
            self.logout()
            return False
            
        query_string = "&".join(params)
        response = self._get(self.ENDPOINTS["index"], query_string)
        
        # Logout dopo l'operazione
        self.logout()
        
        if response:
            _LOGGER.debug(f"Armati programmi: {programmi}")
            return True
        return False
        
    def disarm(self, code: str) -> bool:
        """
        Disarma tutti i programmi.
        
        Args:
            code: Codice allarme
            
        Returns:
            True se comando inviato con successo
        """
        # Login prima
        if not self.login(code):
            return False
        
        # Attesa più lunga per permettere alla centrale di elaborare il login
        time.sleep(1.5)
        
        response = self._get(self.ENDPOINTS["index"], "dummy=0")
        
        # Logout dopo l'operazione
        self.logout()
        
        if response:
            _LOGGER.debug("Disarmato")
            return True
        return False
    
    def reboot(self) -> bool:
        """
        Riavvia il modulo EuroNET.
        
        Chiama direttamente il CGI di reboot che riavvia il modulo.
        Il modulo sarà non disponibile per alcuni secondi durante il riavvio.
        
        Returns:
            True se comando inviato con successo
        """
        try:
            # Chiama direttamente il CGI di reboot
            response = self._get(self.ENDPOINTS["reboot"])
            _LOGGER.warning("Comando reboot EuroNET inviato")
            return True
        except Exception as e:
            _LOGGER.error(f"Errore durante reboot EuroNET: {e}")
            return False
        
    # ========================================================================
    # STATO CENTRALE
    # ========================================================================
    
    def get_stato_centrale(self) -> Optional[StatoCentrale]:
        """
        Ottiene lo stato completo della centrale.
        
        Returns:
            StatoCentrale o None se errore
        """
        xml = self._post(self.ENDPOINTS["status"], self.POST_DATA["stato_impianto"])
        if not xml:
            return None
            
        data = self._parse_xml(xml)
        if not data:
            return None
            
        stato = StatoCentrale()
        stato.datetime = data.get("dtime", "")
        stato.gstate = data.get("gstate", "")
        stato.raw_in_state = data.get("in_state", "")
        
        # Parse gstate
        gstate = stato.gstate
        stato.g1 = "1" in gstate
        stato.g2 = "2" in gstate
        stato.g3 = "3" in gstate
        stato.gext = "4" in gstate
        stato.modo_servizio = "S" in gstate
        stato.logout = "L" in gstate
        
        if "F" in gstate:
            stato.stato = "F"  # Fault
        elif "S" in gstate:
            stato.stato = "S"  # Servizio
        elif "O" in gstate:
            stato.stato = "O"  # Zone Open
        elif "K" in gstate:
            stato.stato = "K"  # OK
            
        # Parse in_state
        in_state = stato.raw_in_state
        if in_state and "%" in in_state:
            self._parse_stato_impianto(in_state, stato)
            
        return stato
        
    def _parse_stato_impianto(self, in_state: str, stato: StatoCentrale):
        """Parsa i valori temp[0-9] dallo stato impianto."""
        parts = in_state.split("%")
        temp = [int(p) if p else 0 for p in parts if p != '']
        
        if len(temp) < 10:
            return
            
        # temp[0] - Stato generale
        stato.rete_220v = bool(temp[0] & 1)
        stato.batteria_interna_ok = bool(temp[0] & 2)
        stato.allarme = bool(temp[0] & 4)
        stato.guasto = bool(temp[0] & 16)
        stato.batteria_esterna_ok = bool(temp[0] & 32)
        stato.sabotaggio_centrale = bool(temp[0] & 64)
        stato.sabotaggio_allarme_ingresso = bool(temp[0] & 128)
        
        # temp[1] - Memorie
        stato.memoria_sabotaggio_centrale = bool(temp[1] & 1)
        stato.memoria_sabotaggio_allarme_ingresso = bool(temp[1] & 2)
        stato.memoria_integrita_bus = bool(temp[1] & 8)
        
        # temp[2] - Sabotaggi BUS
        stato.sabotaggio_dispositivi_bus = bool(temp[2] & 16)
        stato.allarme_integrita_bus = bool(temp[2] & 32)
        stato.memoria_sabotaggio_dispositivi_bus = bool(temp[2] & 16)
        
        # temp[3] - Fusibili
        stato.fusibile_uscite_ok = not bool(temp[3] & 16)
        
        # temp[4-7] - Valori analogici
        stato.tensione_batteria = round(temp[4] / 46.4, 2)
        stato.release_sw = round(temp[5] / 100, 2)
        stato.tensione_bus = round(temp[6] / 183, 2)
        stato.temperatura = round((temp[7] - 2000) / 12, 1)
        
        # temp[8] - Espansioni
        stato.espansione_1 = bool(temp[8] & 1)
        stato.espansione_2 = bool(temp[8] & 2)
        stato.espansione_3 = bool(temp[8] & 4)
        stato.espansione_4 = bool(temp[8] & 8)
        stato.espansione_5 = bool(temp[8] & 16)
        stato.espansione_radio = bool(temp[8] & 32)
        stato.conflitto_espansione_radio = bool(temp[8] & 64)
        
        # temp[9] - Ingressi
        stato.ingressi_esclusi = bool(temp[9] & 1)
        stato.ingressi_aperti = bool(temp[9] & 2)
        stato.sabotaggio_ingressi = bool(temp[9] & 4)
        stato.memoria_sabotaggio_ingressi = bool(temp[9] & 128)
        
    # ========================================================================
    # STATO ZONE FILARI
    # ========================================================================
    
    def get_stato_zone_filari(self, num_zone: int = 35) -> List[StatoZonaFilare]:
        """
        Ottiene lo stato di tutte le zone filari (1-35).
        
        Il formato è: 5 bitmask separati da virgola
        - temp[0]: allarme_24h (bit i = zona i+1)
        - temp[1]: aperta (bit i = zona i+1)
        - temp[2]: esclusa (bit i = zona i+1)
        - temp[3]: memoria_24h (bit i = zona i+1)
        - temp[4]: memoria_allarme (bit i = zona i+1)
        
        Args:
            num_zone: Numero massimo zone da restituire (default 35)
        
        Returns:
            Lista di StatoZonaFilare
        """
        xml = self._post(self.ENDPOINTS["status"], self.POST_DATA["ingressi_filari"])
        if not xml:
            return []
            
        data = self._parse_xml(xml)
        if not data:
            return []
            
        in_state = data.get("in_state", "")
        if not in_state or "," not in in_state:
            return []
            
        # Parse 5 bitmask
        values = [int(v) if v else 0 for v in in_state.strip(",").split(",")]
        
        if len(values) < 5:
            return []
            
        # 5 colonne bitmask: allarme_24h, aperta, esclusa, memoria_24h, memoria_allarme
        zone = []
        for i in range(min(num_zone, 35)):
            bit = 1 << i
            zona = StatoZonaFilare(
                numero=i + 1,
                allarme_24h=bool(values[0] & bit),
                aperta=bool(values[1] & bit),
                esclusa=bool(values[2] & bit),
                memoria_24h=bool(values[3] & bit),
                memoria_allarme=bool(values[4] & bit)
            )
            zone.append(zona)
                
        return zone
        
    def get_stato_zona_filare(self, numero: int) -> Optional[StatoZonaFilare]:
        """
        Ottiene lo stato di una singola zona filare.
        
        Args:
            numero: Numero zona (1-35)
            
        Returns:
            StatoZonaFilare o None
        """
        if not 1 <= numero <= 35:
            return None
            
        xml = self._post(self.ENDPOINTS["status"], f"In={numero}")
        if not xml:
            return None
            
        data = self._parse_xml(xml)
        if not data:
            return None
            
        in_state = data.get("in_state", "")
        
        return StatoZonaFilare(
            numero=numero,
            esclusa="E" in in_state,
            aperta="O" in in_state,
            allarme_24h="A" in in_state,
            memoria_allarme="M" in in_state,
            memoria_24h="B" in in_state
        )
        
    # ========================================================================
    # STATO ZONE RADIO
    # ========================================================================
    
    def get_stato_zone_radio(self, gruppo: int = 0) -> List[StatoZonaRadio]:
        """
        Ottiene lo stato delle zone radio (10 alla volta).
        
        Args:
            gruppo: 0=1-10, 1=11-20, ..., 6=61-64
            
        Returns:
            Lista di StatoZonaRadio
        """
        if not 0 <= gruppo <= 6:
            return []
            
        xml = self._post(self.ENDPOINTS["status"], f"Can={gruppo}")
        if not xml:
            return []
            
        data = self._parse_xml(xml)
        if not data:
            return []
            
        in_state = data.get("in_state", "")
        if not in_state or "," not in in_state:
            return []
            
        values = [int(v) if v else 0 for v in in_state.split(",")]
        
        if len(values) < 6:
            return []
            
        # 6 colonne bitmask: allarme24h, memoria24h, aperta, memoria_allarme, supervisione, batteria
        zone = []
        base_numero = gruppo * 10 + 1
        
        for i in range(10):
            if gruppo == 6 and i >= 4:  # Gruppo 6 ha solo 4 zone (61-64)
                break
                
            bit = 1 << i
            zona = StatoZonaRadio(
                numero=base_numero + i,
                allarme_24h=bool(values[0] & bit),
                memoria_24h=bool(values[1] & bit),
                aperta=bool(values[2] & bit),
                memoria_allarme=bool(values[3] & bit),
                supervisione=bool(values[4] & bit),
                batteria_scarica=bool(values[5] & bit)
            )
            zone.append(zona)
            
        return zone
        
    def get_stato_zona_radio(self, numero: int) -> Optional[StatoZonaRadio]:
        """
        Ottiene lo stato di una singola zona radio.
        
        Args:
            numero: Numero zona (1-64)
            
        Returns:
            StatoZonaRadio o None
        """
        if not 1 <= numero <= 64:
            return None
            
        xml = self._post(self.ENDPOINTS["status"], f"Ca={numero}")
        if not xml:
            return None
            
        data = self._parse_xml(xml)
        if not data:
            return None
            
        in_state = data.get("in_state", "")
        
        return StatoZonaRadio(
            numero=numero,
            batteria_scarica="T" in in_state,
            supervisione="S" in in_state,
            aperta="O" in in_state,
            memoria_allarme="M" in in_state,
            allarme_24h="A" in in_state,
            memoria_24h="B" in in_state
        )
        
    # ========================================================================
    # CONFIGURAZIONE ZONE (HTML SCRAPING)
    # ========================================================================
    
    def get_config_zona_filare(self, numero: int) -> Optional[ConfigZonaFilare]:
        """
        Ottiene la configurazione di una zona filare.
        
        Args:
            numero: Numero zona (1-35)
            
        Returns:
            ConfigZonaFilare o None
        """
        if not 1 <= numero <= 35:
            return None
            
        html = self._get(self.ENDPOINTS["zone_filari_config"], str(numero))
        if not html:
            return None
            
        parser = ZonaFilareParser()
        try:
            config = parser.parse(html)
            config.numero = numero
            return config
        except Exception as e:
            _LOGGER.error(f"Errore parsing zona filare {numero}: {e}")
            return None
            
    def get_config_zona_radio(self, numero: int) -> Optional[ConfigZonaRadio]:
        """
        Ottiene la configurazione di una zona radio.
        
        Args:
            numero: Numero zona (1-64)
            
        Returns:
            ConfigZonaRadio o None
        """
        if not 1 <= numero <= 64:
            return None
            
        html = self._get(self.ENDPOINTS["zone_radio_config"], str(numero))
        if not html:
            return None
            
        parser = ZonaRadioParser()
        try:
            config = parser.parse(html)
            config.numero = numero
            return config
        except Exception as e:
            _LOGGER.error(f"Errore parsing zona radio {numero}: {e}")
            return None
            
    # ========================================================================
    # CONFIGURAZIONE TEMPI (HTML SCRAPING)
    # ========================================================================
    
    def get_config_tempi(self) -> Optional[ConfigTempi]:
        """
        Ottiene la configurazione dei tempi.
        
        Returns:
            ConfigTempi o None
        """
        html = self._get(self.ENDPOINTS["tempi_config"])
        if not html:
            return None
            
        parser = TempiParser()
        try:
            return parser.parse(html)
        except Exception as e:
            _LOGGER.error(f"Errore parsing tempi: {e}")
            return None
            
    # ========================================================================
    # UTILITY
    # ========================================================================
    
    def test_connection(self) -> bool:
        """
        Testa la connessione alla centrale.
        
        Returns:
            True se connessione OK
        """
        stato = self.get_stato_centrale()
        return stato is not None
    
    # ========================================================================
    # CONFIGURAZIONE ZONE (HTML SCRAPING)
    # ========================================================================
    
    def get_zone_filare_config_html(self, numero: int) -> Optional[str]:
        """
        Ottiene l'HTML della pagina configurazione zona filare.
        
        Args:
            numero: Numero zona (1-35)
            
        Returns:
            HTML della pagina o None se errore
        """
        url = f"{self.base_url}/ingresso-filari.html?{numero}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 200:
                # Verifica che non sia una pagina di loading o NoLogin
                text = response.text
                if "NoLogin" in response.url or "NoLogin" in text[:500]:
                    _LOGGER.debug(f"Sessione scaduta su zona filare {numero}")
                    return None
                if "In attesa" in text:
                    _LOGGER.debug(f"Pagina loading per zona filare {numero}")
                    return None
                return text
            _LOGGER.debug(f"HTTP {response.status_code} per zona filare {numero}")
            return None
        except Exception as e:
            _LOGGER.debug(f"Errore fetch zona filare {numero}: {e}")
            return None
    
    def get_zone_radio_config_html(self, numero: int) -> Optional[str]:
        """
        Ottiene l'HTML della pagina configurazione zona radio.
        
        Args:
            numero: Numero zona (1-64)
            
        Returns:
            HTML della pagina o None se errore
        """
        url = f"{self.base_url}/ingresso-radio.html?{numero}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 200:
                # Verifica che non sia una pagina di loading o NoLogin
                text = response.text
                if "NoLogin" in response.url or "NoLogin" in text[:500]:
                    _LOGGER.debug(f"Sessione scaduta su zona radio {numero}")
                    return None
                if "In attesa" in text:
                    _LOGGER.debug(f"Pagina loading per zona radio {numero}")
                    return None
                return text
            _LOGGER.debug(f"HTTP {response.status_code} per zona radio {numero}")
            return None
        except Exception as e:
            _LOGGER.debug(f"Errore fetch zona radio {numero}: {e}")
            return None
