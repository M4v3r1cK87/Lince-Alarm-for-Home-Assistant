"""Physical map parser for Gold centrals - from physicalMap.js"""
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from .byte_utils import (
    hexstring_to_bcd, bcd2int, int2bcd, 
    array_int_to_string, string_to_array_int, 
    hexstring_to_array_int
)

_LOGGER = logging.getLogger(__name__)

# Costanti
MSG_ETICHETTE = ["benvenuto", "allarme", "sabotaggio", "antipanico", "silenzioso", "coda"]

RF_PERIFERICHE = [
    {"nome": "non disponibile", "specs": [None]},
    {"nome": "radiocomando", "specs": ["normale", "antipanico"]},
    {"nome": "movimento", "specs": ["bobby", "baby", "dt", "180"]},
    {"nome": "contatto", "specs": ["magnetico", "tapparella"]},
    {"nome": "sirena", "specs": [None]},
    {"nome": "uscita", "specs": [None]},
    {"nome": "tecnologico", "specs": ["allagamento", "fumo", "gas", "corrente"]},
    {"nome": "ripetitore", "specs": [None]},
    {"nome": "nebbiogeno", "specs": [None]}
]

BUS_PERIFERICHE = {
    6: "tastiera",
    7: "espansione uscite",
    8: "espansione ingressi",
    9: "inseritore",
    11: "tastiera touch"
}


def b2jCodice(arr: List) -> Dict[str, Any]:
    """Parse codice from bytes to JSON."""
    arr[0] = hexstring_to_array_int(arr[0], True)
    
    if len(arr[0]) < 5 or arr[0][4] == 0 or arr[0][4] == 0xFF:
        return {
            "available": True,
            "g1": False,
            "g2": False,
            "g3": False,
            "elettroserratura": False,
            "ronda": False,
            "silenzioso": False,
            "antipanico": False,
            "tipo_utente": False,
            "tipo_codice": False,
            "nome": "Non disponibile"
        }
    
    return {
        "available": False,
        "g1": bool(arr[0][3] & 1),
        "g2": bool(arr[0][3] & 2),
        "g3": bool(arr[0][3] & 4),
        "elettroserratura": bool(arr[0][3] & 16),
        "ronda": bool(arr[0][3] & 32),
        "silenzioso": bool(arr[0][3] & 64),
        "antipanico": bool(arr[0][3] & 128),
        "tipo_utente": arr[0][4] & 7,
        "tipo_codice": bool(arr[0][4] & 128),
        "nome": arr[1].strip() if len(arr) > 1 and arr[1] else ""
    }


def b2jChiave(arr: List) -> Dict[str, Any]:
    """Parse chiave from bytes to JSON."""
    arr[0] = hexstring_to_array_int(arr[0], True)
    
    codice = 0
    if len(arr[0]) >= 3:
        codice = (arr[0][2] << 16) | (arr[0][1] << 8) | arr[0][0]
    
    return {
        "codice": codice,
        "available": False,
        "g1": bool(arr[0][3] & 1) if len(arr[0]) > 3 else False,
        "g2": bool(arr[0][3] & 2) if len(arr[0]) > 3 else False,
        "g3": bool(arr[0][3] & 4) if len(arr[0]) > 3 else False,
        "elettroserratura": bool(arr[0][3] & 16) if len(arr[0]) > 3 else False,
        "ronda": bool(arr[0][3] & 32) if len(arr[0]) > 3 else False,
        "silenzioso": bool(arr[0][3] & 64) if len(arr[0]) > 3 else False,
        "antipanico": bool(arr[0][3] & 128) if len(arr[0]) > 3 else False,
        "tipo_utente": (arr[0][4] & 7) if len(arr[0]) > 4 else 0,
        "tipo_codice": bool(arr[0][4] & 128) if len(arr[0]) > 4 else False,
        "nome": arr[1].strip() if len(arr) > 1 and arr[1] else ""
    }


def b2jFilareRadio(arr: List[int]) -> Dict[str, bool]:
    """Parse common filare/radio attributes."""
    return {
        "test": bool(arr[0] & 1),
        "escluso": bool(arr[0] & 2),
        "ronda": bool(arr[0] & 4),
        "fuoco": bool(arr[0] & 8),
        "campanello": bool(arr[0] & 16),
        "silenzioso": bool(arr[0] & 32),
        "elettroserratura": bool(arr[0] & 64),
        "parzializzabile": bool(arr[0] & 128),
        "g1": bool(arr[1] & 1),  # USCITA/NEBBIOGENO A
        "g2": bool(arr[1] & 2),  # USCITA/NEBBIOGENO Fuoco
        "g3": bool(arr[1] & 4),  # USCITA/NEBBIOGENO Silenzioso
        "a": bool(arr[1] & 8),   # USCITA/NEBBIOGENO Campanello
        "k": bool(arr[1] & 16),  # USCITA/NEBBIOGENO/RADIOCOMANDO Elettroserratura
        "ritardato": bool(arr[1] & 32),  # USCITA/NEBBIOGENO K /RADIOCOMANDO Ronda
        "percorso": bool(arr[1] & 64),   # USCITA/NEBBIOGENO GSM /RADIOCOMANDO Silenzioso
        "sempre_attivo": bool(arr[1] & 128),  # RADIOCOMANDO Antipanico
        "antintrusione": arr[1]
    }


def b2jFilare(arr: List) -> Dict[str, Any]:
    """Parse filare from bytes to JSON."""
    arr[0] = hexstring_to_array_int(arr[0], True)
    
    if len(arr[0]) < 6:
        return {"nome": "Non disponibile"}
    
    generali = b2jFilareRadio([arr[0][0], arr[0][1]])
    parametri = {
        "tempo_trigger": arr[0][2] & 1,
        "tipologia_ingresso": arr[0][2] & 6,
        "doppio_impulso": bool(arr[0][2] & 8),
        "tempo_ingresso": arr[0][3],
        "tempo_uscita": arr[0][4],
        "cicli_autoesclusione": arr[0][5] & 15,
        "nome": arr[1].strip() if len(arr) > 1 and arr[1] else ""
    }
    
    return {**generali, **parametri}


def b2jRadio(arr: List) -> Dict[str, Any]:
    """Parse radio device from bytes to JSON."""
    arr[0] = hexstring_to_array_int(arr[0], True)
    
    # Check validity
    if len(arr[0]) < 14 or not arr[0][8] or arr[0][8] > 8:
        return {
            "num_tipo_periferica": 0,
            "num_spec_periferica": 0,
            "tipo_spec": 0,
            "nome": "Non disponibile"
        }
    
    generali = b2jFilareRadio([arr[0][0], arr[0][1]])
    
    parametri = {
        "tempo_ingresso": arr[0][3],
        "tempo_uscita": arr[0][4],
        "cicli_autoesclusione": arr[0][5],
        "indirizzo_periferica": (arr[0][7] << 8) + arr[0][6],
        "num_tipo_periferica": arr[0][8],
        "num_spec_periferica": arr[0][9],
        "tipo_spec": (arr[0][9] << 4) + arr[0][8],
        "tipo_periferica": RF_PERIFERICHE[arr[0][8]]["nome"],
        "specializzazione_periferica": RF_PERIFERICHE[arr[0][8]]["specs"][arr[0][9]] if arr[0][9] < len(RF_PERIFERICHE[arr[0][8]]["specs"]) else None,
        "mw": arr[0][10],
        "pir1": arr[0][11],
        "pir2": arr[0][12],
        "am": arr[0][13],
        "nome": arr[1].strip() if len(arr) > 1 and arr[1] else ""
    }
    
    parametri["gruppo_spec"] = parametri["tipo_spec"] if parametri["tipo_spec"] != 0x11 else 0x01
    
    # Parse specific device parameters
    sub = ""
    tipo = arr[0][8]
    spec = arr[0][9]
    
    if tipo == 1:  # radiocomando
        sub = "Radiocomando Antipanico" if spec else "Radiocomando"
        
    elif tipo == 2:  # movimento
        parametri["supervisione"] = bool(arr[0][2] & 1)
        parametri["led_on"] = bool(arr[0][2] & 2)
        parametri["cd_cs"] = arr[0][2] & 24
        
        if parametri["tipo_spec"] == 0x22:  # DT
            parametri["logica"] = 0x40 if (arr[0][2] & 224) != 0 else 0
        elif parametri["tipo_spec"] == 0x32:  # 180
            parametri["reed"] = 1 if bool(arr[0][2] & 4) else 0
            parametri["prog"] = bool(arr[0][2] & 32)
            parametri["logica"] = arr[0][2] & 192
        else:  # BOBBY BABY
            parametri["logica"] = arr[0][2] & 224
        
        sub = "Tenda" if spec == 1 else ("DT" if spec == 2 else "Vol. Esterno")
        
    elif tipo == 3:  # contatto
        parametri["supervisione"] = bool(arr[0][2] & 1)
        parametri["led_on"] = bool(arr[0][2] & 2)
        parametri["reed"] = 0 if bool(arr[0][2] & 4) else 1
        parametri["aux1"] = bool(arr[0][2] & 8)
        parametri["aux2"] = bool(arr[0][2] & 16)
        parametri["prog"] = bool(arr[0][2] & 32)
        parametri["impulsi"] = arr[0][2] & 192
        
        if parametri["aux1"]:
            parametri["aux"] = 0
        else:
            parametri["aux"] = 1 if parametri["impulsi"] == 0 else (2 if parametri["impulsi"] == 64 else 3)
        
        parametri["associazione"] = (arr[0][2] >> 4) & 0x03
        sub = "Tapparella" if spec else "Contatto"
        
    elif tipo == 4:  # sirena
        parametri["supervisione"] = bool(arr[0][2] & 1)
        parametri["led_on"] = bool(arr[0][2] & 2)
        parametri["allarme_a"] = bool(arr[0][2] & 4)
        parametri["ring"] = bool(arr[0][2] & 8)
        parametri["sabotaggio"] = bool(arr[0][2] & 16)
        parametri["tamper"] = bool(arr[0][2] & 32)
        parametri["tipo_suono"] = arr[0][2] & 64
        parametri["allarme_k"] = bool(arr[0][2] & 128)
        sub = "Sirena"
        
    elif tipo == 5:  # uscita
        parametri["supervisione"] = bool(arr[0][2] & 1)
        parametri["led_on"] = bool(arr[0][2] & 2)
        parametri["abilita_impianto_attivo"] = bool(arr[0][2] & 4)
        parametri["abilita_ingressi"] = bool(arr[0][2] & 8)
        parametri["abilita_and_mode"] = bool(arr[0][2] & 16)
        parametri["nc"] = bool(arr[0][2] & 32)
        parametri["attributi"] = bool(arr[0][2] & 128)
        sub = "Uscita"
        
    elif tipo == 6:  # tecnologico
        parametri["supervisione"] = bool(arr[0][2] & 1)
        parametri["led_on"] = bool(arr[0][2] & 2)
        sub = "Fumo" if spec else "Allagamento"
        
    elif tipo == 7:  # ripetitore
        sub = "Ripetitore"
        
    elif tipo == 8:  # nebbiogeno
        parametri["supervisione"] = bool(arr[0][2] & 1)
        parametri["led_on"] = bool(arr[0][2] & 2)
        parametri["abilita_ingressi"] = bool(arr[0][2] & 8)
        parametri["and"] = bool(arr[0][2] & 16)
        parametri["antipanico"] = bool(arr[0][2] & 32)
        sub = "Nebbiogeno"
    
    return {**generali, **parametri, "sub": sub}


def b2jTel(arr: List) -> Dict[str, Any]:
    """Parse telephone number configuration."""
    arr[1] = hexstring_to_array_int(arr[1], True)
    
    if len(arr[1]) < 5:
        return {"numero": "", "nome": "Non disponibile"}
    
    return {
        "ripetizioni": arr[1][0] & 15,
        "sms_credito_scadenza": bool(arr[1][0] & 16),
        "abilitazione": bool(arr[1][0] & 32),
        "vocale_a": bool(arr[1][1] & 1),
        "vocale_k": bool(arr[1][1] & 2),
        "vocale_sabotaggio": bool(arr[1][1] & 4),
        "vocale_silenzioso": bool(arr[1][1] & 8),
        "sms_a": bool(arr[1][1] & 16),
        "sms_k": bool(arr[1][1] & 32),
        "sms_sabotaggio": bool(arr[1][1] & 64),
        "sms_silenzioso": bool(arr[1][1] & 128),
        "sms_batteria_centrale_carica": bool(arr[1][2] & 1),
        "sms_batteria_radio_carica": bool(arr[1][2] & 2),
        "sms_rete_elettrica_assente": bool(arr[1][2] & 4),
        "sms_rete_elettrica_ripristinata": bool(arr[1][2] & 8),
        "sms_variazione_programmi": bool(arr[1][2] & 16),
        "sms_accesso_sistema": bool(arr[1][2] & 32),
        "squillo_esistenza_vita": bool(arr[1][3] & 1),
        "sms_esistenza_vita": bool(arr[1][3] & 2),
        "squillo_conferma_uscite": bool(arr[1][3] & 4),
        "sms_conferma_uscite": bool(arr[1][3] & 8),
        "vocale_conferma_uscite": bool(arr[1][3] & 16),
        "apri_cancello_na": bool(arr[1][3] & 32),
        "apri_cancello_out1": bool(arr[1][3] & 64),
        "impulsato": bool(arr[1][3] & 128),
        "durata_impulso": arr[1][4],
        "numero": arr[0].strip() if arr[0] else "",
        "nome": arr[2].strip() if len(arr) > 2 and arr[2] else ""
    }


def b2jBus(arr: List) -> Dict[str, Any]:
    """Parse BUS device configuration."""
    arr[0] = hexstring_to_array_int(arr[0], True)
    
    if len(arr[0]) < 4 or arr[0][2] == 0 or arr[0][2] == 0xFF:
        return {
            "identificativo": 0,
            "tipo": "",
            "num_tipo_periferica": 0,
            "espansione": 0,
            "nome": "Non disponibile"
        }
    
    return {
        "identificativo": (arr[0][1] << 8) + arr[0][0],
        "tipo": BUS_PERIFERICHE.get(arr[0][2], ""),
        "num_tipo_periferica": arr[0][2],
        "espansione": arr[0][3],
        "nome": arr[1].strip() if len(arr) > 1 and arr[1] else ""
    }


def b2jTempi(hexstring: str) -> Dict[str, int]:
    """Parse tempi configuration."""
    arr = hexstring_to_array_int(hexstring, False)
    
    if len(arr) < 8:
        return {}
    
    return {
        "allarme": (arr[0] << 8) + (arr[1] & 0xFF),
        "fuoco": arr[2],
        "silenzioso": arr[3] // 2,
        "campanello": arr[4] // 2,
        "elettroserratura": arr[5] // 2,
        "ronda": (arr[6] << 8) + (arr[7] & 0xFF)
    }


def b2jOpzioni(hexstring: str) -> Dict[str, bool]:
    """Parse opzioni configuration."""
    arr = hexstring_to_array_int(hexstring, False)
    
    if len(arr) < 2:
        return {}
    
    return {
        "toni_ins": bool(arr[0] & 1),
        "toni_ingr": bool(arr[0] & 2),
        "led_on": bool(arr[0] & 4),
        "autoreset": bool(arr[0] & 8),
        "rit_no_rete": bool(arr[0] & 16),
        "all_falsa_chiave": bool(arr[0] & 32),
        "chiave_base": bool(arr[0] & 64),
        "buzzer": bool(arr[0] & 128),
        "abil_campanello": bool(arr[1] & 1),
        "abil_asterisco": bool(arr[1] & 2),
        "des": bool(arr[1] & 4),
        "inversione": bool(arr[1] & 8),
        "antimask": bool(arr[1] & 16),
        "supervisione": bool(arr[1] & 32)
    }


def b2jSupertasti(value: int) -> Dict[str, bool]:
    """Parse supertasti configuration."""
    return {
        "supertasto1": bool(value & 2),
        "supertasto2": bool(value & 4),
        "supertasto3": bool(value & 8),
        "supertasto4": bool(value & 16)
    }


def b2jUscita(value: int) -> Dict[str, Any]:
    """Parse single uscita configuration."""
    return {
        "polarita": "normale" if (value & 128) == 0 else "invertita",
        "attributo": value & (~(1 << 7))
    }


def b2jUscite(hexstring: str) -> Dict[str, Dict[str, Any]]:
    """Parse uscite configuration."""
    arr = hexstring_to_array_int(hexstring, True)
    
    if len(arr) < 5:
        return {}
    
    return {
        "uscita0": b2jUscita(arr[1]),
        "uscita1": b2jUscita(arr[2]),
        "uscita2": b2jUscita(arr[3]),
        "uscita3": b2jUscita(arr[4]),
        "uscita4": b2jUscita(arr[0])
    }


def b2jGsm(hexstring: str) -> Dict[str, Any]:
    """Parse GSM configuration."""
    arr = hexstring_to_array_int(hexstring, True)
    
    if len(arr) < 12:
        return {}
    
    # Parse esistenza_in_vita (DHM)
    giorni = bcd2int(arr[5]) if len(arr) > 5 else 0
    ore = bcd2int(arr[3]) if len(arr) > 3 else 0
    minuti = bcd2int(arr[4]) if len(arr) > 4 else 0
    esistenza_in_vita = (giorni * 24 * 60) + (ore * 60) + minuti
    
    # Parse scadenza_sim date
    anno = 2000 + bcd2int(arr[8]) if len(arr) > 8 else 2000
    mese = bcd2int(arr[7]) - 1 if len(arr) > 7 else 0  # -1 perché in JS i mesi sono 0-based
    giorno = bcd2int(arr[6]) if len(arr) > 6 else 1
    
    return {
        "opzioni": {
            "accesso_telegestione": bool(arr[0] & 1),
            "visualizzazione_chiamate": bool(arr[0] & 2),
            "on": bool(arr[0] & 4),
            "gestione_credito": bool(arr[0] & 16),
            "gestione_disturbo": bool(arr[0] & 32)
        },
        "numero_tentativi_chiamate": arr[1],
        "numero_squilli_risposta": arr[2],
        "esistenza_in_vita": esistenza_in_vita,
        "scadenza_sim": datetime(anno, mese + 1, giorno),  # +1 perché Python usa 1-12
        "giorni_scadenza_sim": arr[9],
        "giorni_credito_minimo": arr[10],
        "credito_minimo": arr[11]
    }


def b2jAutoIns(hexstring: str) -> Dict[str, Dict[str, Any]]:
    """Parse auto-inserimento configuration."""
    arr = hexstring_to_array_int(hexstring, False)
    
    if len(arr) < 8:
        return {}
    
    return {
        "totale": {
            "tempo": (bcd2int(arr[0] & 0x7F) * 60) + bcd2int(arr[1]),
            "abilitato": bool(arr[0] & 0x80)
        },
        "g1": {
            "tempo": (bcd2int(arr[2] & 0x7F) * 60) + bcd2int(arr[3]),
            "abilitato": bool(arr[2] & 0x80)
        },
        "g2": {
            "tempo": (bcd2int(arr[4] & 0x7F) * 60) + bcd2int(arr[5]),
            "abilitato": bool(arr[4] & 0x80)
        },
        "g3": {
            "tempo": (bcd2int(arr[6] & 0x7F) * 60) + bcd2int(arr[7]),
            "abilitato": bool(arr[6] & 0x80)
        }
    }


def parsePhysicalMap(physical_map: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse complete physical map.
    """
    _LOGGER.debug("Parsing Gold physical map")
    
    try:
        # Parse messages
        msg_parsed = {}
        if "msg" in physical_map:
            msgs = physical_map["msg"]
            for i, msg in enumerate(msgs):
                group = f"gr{i // 2}"
                label = MSG_ETICHETTE[i % len(MSG_ETICHETTE)]
                if group not in msg_parsed:
                    msg_parsed[group] = {}
                msg_parsed[group][label] = msg[0].strip() if msg and len(msg) > 0 else ""
        
        result = {
            "model": physical_map.get("model"),
            "rfversion": hexstring_to_bcd(physical_map.get("rfversion", "")),
            "version": hexstring_to_bcd(physical_map.get("version", "")),
            "ora_ls": physical_map.get("ora_ls"),
            "tempi": b2jTempi(physical_map.get("tempi", "")),
            "opzioni": b2jOpzioni(physical_map.get("opzioni", "")),
            "supertasti": b2jSupertasti(physical_map.get("suptasti", 0)),
            "uscite": b2jUscite(physical_map.get("uscite", "")),
            "pos_eventi": 0,
            "autoins": b2jAutoIns(physical_map.get("autoins", "")),
            "gsm": b2jGsm(physical_map.get("gsm", "")),
            "cicli_sup": physical_map.get("cicli_sup"),
            "intest": array_int_to_string(hexstring_to_array_int(physical_map.get("intest", ""))),
            "wifi_set": {
                "on": bool(physical_map.get("wifi_set", 0) & 1),
                "conn": "locale" if bool(physical_map.get("wifi_set", 0) & 2) else "cloud",
                "gprs": bool(physical_map.get("wifi_set", 0) & 4),
                "value": physical_map.get("wifi_set", 0)
            },
            "app_name": physical_map.get("app_name", ""),
            "codici": [b2jCodice(x) for x in physical_map.get("codici", [])],
            "filari": [b2jFilare(x) for x in physical_map.get("filari", [])],
            "radio": [x for x in [b2jRadio(x) for x in physical_map.get("radio", [])] if x],
            "bus": [b2jBus(x) for x in physical_map.get("bus", [])],
            "tel": [b2jTel(x) for x in physical_map.get("tel", [])],
            "msg": msg_parsed
        }
        
        # Parse pos_eventi
        if "pos_eventi" in physical_map:
            arr = hexstring_to_array_int(physical_map["pos_eventi"], True)
            if len(arr) >= 2:
                result["pos_eventi"] = (arr[0] << 8) + arr[1]
        
        _LOGGER.debug("Physical map parsed successfully")
        return result
        
    except Exception as e:
        _LOGGER.error(f"Error parsing physical map: {e}", exc_info=True)
        return {}


class GoldPhysicalMapParser:
    """Parser class for Gold physical map."""
    
    def __init__(self):
        """Initialize parser."""
        self._last_map = None
        _LOGGER.debug("GoldPhysicalMapParser initialized")
    
    def parse(self, physical_map: Dict[str, Any]) -> Dict[str, Any]:
        """Parse physical map."""
        self._last_map = parsePhysicalMap(physical_map)
        return self._last_map
    
    def get_codici(self) -> List[Dict[str, Any]]:
        """Get parsed codici."""
        if self._last_map:
            return self._last_map.get("codici", [])
        return []
    
    def get_filari(self) -> List[Dict[str, Any]]:
        """Get parsed filari."""
        if self._last_map:
            return self._last_map.get("filari", [])
        return []
    
    def get_radio(self) -> List[Dict[str, Any]]:
        """Get parsed radio devices."""
        if self._last_map:
            return self._last_map.get("radio", [])
        return []
    
    def get_bus(self) -> List[Dict[str, Any]]:
        """Get parsed bus devices."""
        if self._last_map:
            return self._last_map.get("bus", [])
        return []
    
    def get_tel(self) -> List[Dict[str, Any]]:
        """Get parsed telephone numbers."""
        if self._last_map:
            return self._last_map.get("tel", [])
        return []
    
    @staticmethod
    def parse_radio_config(config_hex: str) -> Dict[str, Any]:
        """
        Parse configurazione radio da hex string.
        
        Il formato è quello della physical map Gold:
        byte 8 = num_tipo_periferica
        byte 9 = num_spec_periferica
        
        Args:
            config_hex: Stringa esadecimale della configurazione
            
        Returns:
            Dict con num_tipo_periferica, num_spec_periferica e altri campi
        """
        result = {
            "num_tipo_periferica": 0,
            "num_spec_periferica": 0,
            "tipo_periferica": "non disponibile",
            "specializzazione_periferica": None
        }
        
        try:
            if not config_hex or len(config_hex) < 20:
                return result
            
            # Converti hex string in array di byte
            arr = hexstring_to_array_int(config_hex, True)
            
            if len(arr) < 10:
                return result
            
            num_tipo = arr[8] if len(arr) > 8 else 0
            num_spec = arr[9] if len(arr) > 9 else 0
            
            if num_tipo == 0 or num_tipo > 8:
                return result
            
            result["num_tipo_periferica"] = num_tipo
            result["num_spec_periferica"] = num_spec
            
            # Nomi tipo periferica
            if num_tipo < len(RF_PERIFERICHE):
                result["tipo_periferica"] = RF_PERIFERICHE[num_tipo]["nome"]
                specs = RF_PERIFERICHE[num_tipo]["specs"]
                if num_spec < len(specs) and specs[num_spec]:
                    result["specializzazione_periferica"] = specs[num_spec]
            
            # Altri campi utili
            result["indirizzo_periferica"] = ((arr[7] << 8) + arr[6]) if len(arr) > 7 else 0
            result["tempo_ingresso"] = arr[3] if len(arr) > 3 else 0
            result["tempo_uscita"] = arr[4] if len(arr) > 4 else 0
            
        except Exception as e:
            _LOGGER.debug(f"Error parsing radio config: {e}")
        
        return result
    
    @staticmethod
    def parse_bus_config(config_hex: str) -> Dict[str, Any]:
        """
        Parse configurazione bus da hex string.
        
        Args:
            config_hex: Stringa esadecimale della configurazione
            
        Returns:
            Dict con identificativo, tipo, num_tipo_periferica
        """
        result = {
            "identificativo": 0,
            "tipo": "",
            "num_tipo_periferica": 0,
            "espansione": 0
        }
        
        try:
            if not config_hex or len(config_hex) < 8:
                return result
            
            arr = hexstring_to_array_int(config_hex, True)
            
            if len(arr) < 4:
                return result
            
            if arr[2] == 0 or arr[2] == 0xFF:
                return result
            
            result["identificativo"] = ((arr[1] << 8) + arr[0])
            result["num_tipo_periferica"] = arr[2]
            result["tipo"] = BUS_PERIFERICHE.get(arr[2], "")
            result["espansione"] = arr[3]
            
        except Exception as e:
            _LOGGER.debug(f"Error parsing bus config: {e}")
        
        return result
    