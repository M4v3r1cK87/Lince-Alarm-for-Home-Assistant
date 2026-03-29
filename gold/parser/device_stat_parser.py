"""Device status parser for Gold centrals.

Traduzione Python di b2jRadioStat, b2jBusStat, b2jFilareStat da physicalMap.js
Usato per interpretare i valori stats[] ricevuti via WebSocket onGoldDevStats.
"""
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)


# Tipi di periferiche radio
RADIO_TYPE_NONE = 0
RADIO_TYPE_RADIOCOMANDO = 1
RADIO_TYPE_MOVIMENTO = 2
RADIO_TYPE_CONTATTO = 3
RADIO_TYPE_SIRENA = 4
RADIO_TYPE_USCITA = 5
RADIO_TYPE_TECNOLOGICO = 6
RADIO_TYPE_RIPETITORE = 7
RADIO_TYPE_NEBBIOGENO = 8

# Specializzazioni tipo 3 (contatto)
SPEC_CONTATTO_MAGNETICO = 0
SPEC_CONTATTO_TAPPARELLA = 1

# Specializzazioni tipo 6 (tecnologico)
SPEC_TECNOLOGICO_ALLAGAMENTO = 0
SPEC_TECNOLOGICO_FUMO = 1
SPEC_TECNOLOGICO_GAS = 2
SPEC_TECNOLOGICO_CORRENTE = 3

# Tipi periferiche BUS
BUS_TYPE_TASTIERA = 6
BUS_TYPE_ESPANSIONE_USCITE = 7
BUS_TYPE_ESPANSIONE_INGRESSI = 8
BUS_TYPE_INSERITORE = 9
BUS_TYPE_TASTIERA_TOUCH = 11


@dataclass
class RadioDeviceStat:
    """Stato di un dispositivo radio."""
    # Allarmi
    allarme: bool = False
    allarme_reed: bool = False  # Contatto magnetico aperto
    allarme_aux: bool = False   # Ingresso ausiliario / tapparella
    allarme_am: bool = False    # Antimask
    allarme_sx: bool = False
    allarme_dx: bool = False
    allarme_frontale: bool = False
    allagamento: bool = False
    fumo: bool = False
    
    # Memorie
    memoria: bool = False
    memoria_reed: bool = False
    memoria_aux: bool = False
    memoria_tamper: bool = False
    
    # Stato generale
    tamper: bool = False
    batteria_scarica: Optional[bool] = None  # None = sconosciuto
    supervisione_led: bool = False
    escluso_led: bool = False
    dormiente: bool = False
    guasto: bool = False
    
    # Uscite/Nebbiogeno
    stato_ingresso: bool = False
    stato_uscita: bool = False
    pronto: bool = False
    bombola_scarica: bool = False
    rete_assente: bool = False
    
    def is_triggered(self) -> bool:
        """Ritorna True se il sensore è in stato di allarme."""
        return (
            self.allarme or 
            self.allarme_reed or 
            self.allarme_aux or 
            self.allarme_am or
            self.allarme_sx or
            self.allarme_dx or
            self.allarme_frontale or
            self.allagamento or
            self.fumo
        )
    
    def has_problem(self) -> bool:
        """Ritorna True se c'è un problema (batteria, tamper, guasto)."""
        return (
            self.tamper or
            self.batteria_scarica == True or
            self.guasto or
            self.bombola_scarica or
            self.rete_assente
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte in dizionario."""
        return {
            "allarme": self.allarme,
            "allarme_reed": self.allarme_reed,
            "allarme_aux": self.allarme_aux,
            "allarme_am": self.allarme_am,
            "allarme_sx": self.allarme_sx,
            "allarme_dx": self.allarme_dx,
            "allarme_frontale": self.allarme_frontale,
            "allagamento": self.allagamento,
            "fumo": self.fumo,
            "memoria": self.memoria,
            "memoria_reed": self.memoria_reed,
            "memoria_aux": self.memoria_aux,
            "memoria_tamper": self.memoria_tamper,
            "tamper": self.tamper,
            "batteria_scarica": self.batteria_scarica,
            "supervisione_led": self.supervisione_led,
            "escluso_led": self.escluso_led,
            "dormiente": self.dormiente,
            "guasto": self.guasto,
            "stato_ingresso": self.stato_ingresso,
            "stato_uscita": self.stato_uscita,
            "pronto": self.pronto,
            "bombola_scarica": self.bombola_scarica,
            "rete_assente": self.rete_assente,
            "is_triggered": self.is_triggered(),
            "has_problem": self.has_problem(),
        }


@dataclass
class BusDeviceStat:
    """Stato di un dispositivo BUS."""
    dispositivo_presente: Optional[bool] = None
    as_: bool = False  # Alimentazione Secondaria
    sabotaggio: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dispositivo_presente": self.dispositivo_presente,
            "as": self.as_,
            "sabotaggio": self.sabotaggio,
        }


@dataclass  
class FilareDeviceStat:
    """Stato di un ingresso filare."""
    ingresso_aperto: bool = False
    allarme_24: bool = False
    ingresso_escluso: bool = False
    memoria_allarme: bool = False
    memoria_allarme_24: bool = False
    
    def is_triggered(self) -> bool:
        return self.ingresso_aperto or self.allarme_24
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ingresso_aperto": self.ingresso_aperto,
            "allarme_24": self.allarme_24,
            "ingresso_escluso": self.ingresso_escluso,
            "memoria_allarme": self.memoria_allarme,
            "memoria_allarme_24": self.memoria_allarme_24,
            "is_triggered": self.is_triggered(),
        }


def parse_radio_stat(num: int, num_tipo_periferica: int, num_spec_periferica: int = 0) -> RadioDeviceStat:
    """
    Parse stato dispositivo radio da valore numerico 16-bit.
    
    Equivalente JavaScript: b2jRadioStat(num, radio)
    
    Args:
        num: Valore 16-bit dallo stats[] del WebSocket
        num_tipo_periferica: Tipo di periferica (1-8)
        num_spec_periferica: Specializzazione (0-3)
    
    Returns:
        RadioDeviceStat con tutti i flag interpretati
    """
    stat = RadioDeviceStat()
    
    # Parse batteria_scarica (comune a tutti)
    # Logica: bit 8 (0x0100) = scarica, bit 3 (0x08) = ok, entrambi 0 = sconosciuto
    if num & 0x0100:
        stat.batteria_scarica = True
    elif num & 0x08:
        stat.batteria_scarica = False
    else:
        stat.batteria_scarica = None
    
    if num_tipo_periferica == RADIO_TYPE_RADIOCOMANDO:
        # case 1: radiocomando
        # Solo batteria (già parsata sopra)
        pass
        
    elif num_tipo_periferica == RADIO_TYPE_MOVIMENTO:
        # case 2: movimento (PIR)
        stat.allarme = bool(num & 0x01)
        stat.tamper = bool(num & 0x02)
        stat.supervisione_led = bool(num & 0x04)
        stat.escluso_led = bool(num & 0x10)
        stat.memoria = bool(num & 0x20)
        stat.dormiente = bool(num & 0x0800)
        stat.allarme_am = bool(num & 0x2000)
        stat.memoria_tamper = bool(num & 0x8000)
        stat.allarme_sx = bool(num & 0x0200)
        stat.allarme_dx = bool(num & 0x0400)
        stat.allarme_frontale = bool(num & 0x4000)
        
    elif num_tipo_periferica == RADIO_TYPE_CONTATTO:
        # case 3: contatto
        if num_spec_periferica == SPEC_CONTATTO_MAGNETICO:
            # Contatto magnetico
            stat.allarme_reed = bool(num & 0x0200)
            stat.allarme_aux = bool(num & 0x0400)
            stat.tamper = bool(num & 0x02)
            stat.supervisione_led = bool(num & 0x04)
            stat.escluso_led = bool(num & 0x10)
            stat.memoria_reed = bool(num & 0x20)
            stat.dormiente = bool(num & 0x0800)
            stat.memoria_tamper = bool(num & 0x8000)
            stat.memoria_aux = False
        elif num_spec_periferica == SPEC_CONTATTO_TAPPARELLA:
            # Tapparella/Tenda
            stat.allarme_aux = bool(num & 0x01)
            stat.supervisione_led = bool(num & 0x04)
            stat.escluso_led = bool(num & 0x10)
            stat.guasto = False
            stat.dormiente = bool(num & 0x0800)
            stat.memoria_aux = bool(num & 0x20)
            
    elif num_tipo_periferica == RADIO_TYPE_SIRENA:
        # case 4: sirena
        stat.tamper = bool(num & 0x02)
        stat.supervisione_led = bool(num & 0x04)
        stat.escluso_led = bool(num & 0x10)
        stat.guasto = bool(num & 0x1000)
        stat.dormiente = bool(num & 0x0800)
        stat.memoria_tamper = bool(num & 0x8000)
        
    elif num_tipo_periferica == RADIO_TYPE_USCITA:
        # case 5: uscita radio
        stat.supervisione_led = bool(num & 0x04)
        stat.escluso_led = bool(num & 0x10)
        stat.dormiente = bool(num & 0x0800)
        stat.stato_ingresso = bool(num & 0x4000)
        stat.stato_uscita = bool(num & 0x2000)
        stat.tamper = bool(num & 0x02)
        stat.memoria_tamper = bool(num & 0x8000)
        
    elif num_tipo_periferica == RADIO_TYPE_TECNOLOGICO:
        # case 6: tecnologico (allagamento, fumo, gas, corrente)
        if num_spec_periferica == SPEC_TECNOLOGICO_ALLAGAMENTO:
            stat.supervisione_led = bool(num & 0x04)
            stat.dormiente = bool(num & 0x0800)
            stat.escluso_led = bool(num & 0x10)
            stat.guasto = bool(num & 0x1000)
            stat.tamper = bool(num & 0x02)
            stat.allagamento = bool(num & 0x4000)
            stat.memoria_tamper = bool(num & 0x8000)
        elif num_spec_periferica == SPEC_TECNOLOGICO_FUMO:
            stat.supervisione_led = bool(num & 0x04)
            stat.escluso_led = bool(num & 0x10)
            stat.dormiente = bool(num & 0x0800)
            stat.guasto = bool(num & 0x1000)
            stat.fumo = bool(num & 0x4000)
        # Gas e Corrente non implementati nel JS originale
            
    elif num_tipo_periferica == RADIO_TYPE_RIPETITORE:
        # case 7: ripetitore (nessun parsing specifico)
        pass
        
    elif num_tipo_periferica == RADIO_TYPE_NEBBIOGENO:
        # case 8: nebbiogeno
        stat.supervisione_led = bool(num & 0x04)
        stat.escluso_led = bool(num & 0x10)
        stat.dormiente = bool(num & 0x0800)
        stat.guasto = bool(num & 0x1000)
        stat.tamper = bool(num & 0x02)
        stat.memoria_tamper = bool(num & 0x8000)
        stat.bombola_scarica = bool(num & 0x0200)
        stat.rete_assente = bool(num & 0x2000)
        stat.pronto = bool(num & 0x4000)
    
    return stat


def parse_bus_stat(num: int, num_tipo_periferica: int) -> BusDeviceStat:
    """
    Parse stato dispositivo BUS da valore numerico.
    
    Equivalente JavaScript: b2jBusStat(num, bus)
    
    Args:
        num: Valore dallo stats[] del WebSocket
        num_tipo_periferica: Tipo di periferica BUS (6,7,8,9,11)
    
    Returns:
        BusDeviceStat con i flag interpretati
    """
    stat = BusDeviceStat()
    
    # dispositivo_presente solo se è un tipo valido
    if num_tipo_periferica > 0:
        stat.dispositivo_presente = bool(num & 0x01)
    else:
        stat.dispositivo_presente = None
    
    # AS solo per espansioni (tipo 7 e 8)
    if num_tipo_periferica in (BUS_TYPE_ESPANSIONE_USCITE, BUS_TYPE_ESPANSIONE_INGRESSI):
        stat.as_ = bool(num & 0x02)
    else:
        stat.as_ = False
    
    # Sabotaggio comune
    stat.sabotaggio = bool(num & 0x08)
    
    return stat


def parse_filare_stat(num: int) -> FilareDeviceStat:
    """
    Parse stato ingresso filare da valore numerico.
    
    Equivalente JavaScript: b2jFilareStat(num)
    
    Args:
        num: Valore dallo stats[] del WebSocket
    
    Returns:
        FilareDeviceStat con i flag interpretati
    """
    stat = FilareDeviceStat()
    
    stat.ingresso_aperto = bool(num & 0x01)
    stat.allarme_24 = bool(num & 0x02)
    stat.ingresso_escluso = bool(num & 0x10)
    stat.memoria_allarme = bool(num & 0x20)
    stat.memoria_allarme_24 = bool(num & 0x0800)
    
    return stat


def parse_dev_stats(
    type_: str, 
    group: int, 
    stats: list, 
    physical_map: Dict[str, Any]
) -> Dict[int, Any]:
    """
    Parse completo degli stats ricevuti via WebSocket onGoldDevStats.
    
    Args:
        type_: "radio", "bus" o "filari"
        group: Gruppo (0-3)
        stats: Array di 16 valori numerici
        physical_map: pm dal login Gold (contiene pm.radio, pm.bus, pm.filari)
    
    Returns:
        Dict con indice dispositivo -> stato parsato
    """
    result = {}
    
    pm_key = "radio" if type_ == "radio" else ("bus" if type_ == "bus" else "filari")
    pm_data = physical_map.get(pm_key, [])
    
    for i, stat_value in enumerate(stats):
        # Indice globale = group * 16 + i
        global_idx = (group * 16) + i
        
        if global_idx >= len(pm_data):
            continue
            
        device_config = pm_data[global_idx]
        
        if type_ == "radio":
            num_tipo = device_config.get("num_tipo_periferica", 0)
            num_spec = device_config.get("num_spec_periferica", 0)
            
            if num_tipo > 0:  # Dispositivo configurato
                parsed = parse_radio_stat(stat_value, num_tipo, num_spec)
                result[global_idx] = {
                    "nome": device_config.get("nome", f"Radio {global_idx}"),
                    "tipo": num_tipo,
                    "spec": num_spec,
                    "raw": stat_value,
                    "stat": parsed.to_dict()
                }
                
        elif type_ == "bus":
            num_tipo = device_config.get("num_tipo_periferica", 0)
            
            if num_tipo > 0:
                parsed = parse_bus_stat(stat_value, num_tipo)
                result[global_idx] = {
                    "nome": device_config.get("nome", f"Bus {global_idx}"),
                    "tipo": num_tipo,
                    "raw": stat_value,
                    "stat": parsed.to_dict()
                }
                
        elif type_ == "filari":
            parsed = parse_filare_stat(stat_value)
            result[global_idx] = {
                "nome": device_config.get("nome", f"Filare {global_idx}"),
                "raw": stat_value,
                "stat": parsed.to_dict()
            }
    
    return result


# Nomi dei tipi periferiche per logging/debug
RADIO_TYPE_NAMES = {
    RADIO_TYPE_NONE: "non disponibile",
    RADIO_TYPE_RADIOCOMANDO: "radiocomando",
    RADIO_TYPE_MOVIMENTO: "movimento",
    RADIO_TYPE_CONTATTO: "contatto",
    RADIO_TYPE_SIRENA: "sirena",
    RADIO_TYPE_USCITA: "uscita",
    RADIO_TYPE_TECNOLOGICO: "tecnologico",
    RADIO_TYPE_RIPETITORE: "ripetitore",
    RADIO_TYPE_NEBBIOGENO: "nebbiogeno",
}

CONTATTO_SPEC_NAMES = {
    SPEC_CONTATTO_MAGNETICO: "magnetico",
    SPEC_CONTATTO_TAPPARELLA: "tapparella",
}

TECNOLOGICO_SPEC_NAMES = {
    SPEC_TECNOLOGICO_ALLAGAMENTO: "allagamento",
    SPEC_TECNOLOGICO_FUMO: "fumo",
    SPEC_TECNOLOGICO_GAS: "gas",
    SPEC_TECNOLOGICO_CORRENTE: "corrente",
}


def get_device_type_name(num_tipo: int, num_spec: int = 0) -> str:
    """Ritorna il nome leggibile del tipo di dispositivo."""
    base_name = RADIO_TYPE_NAMES.get(num_tipo, "sconosciuto")
    
    if num_tipo == RADIO_TYPE_CONTATTO:
        spec_name = CONTATTO_SPEC_NAMES.get(num_spec, "")
        if spec_name:
            return f"{base_name} {spec_name}"
    elif num_tipo == RADIO_TYPE_TECNOLOGICO:
        spec_name = TECNOLOGICO_SPEC_NAMES.get(num_spec, "")
        if spec_name:
            return f"{base_name} {spec_name}"
    
    return base_name
