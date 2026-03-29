"""Gold parser module."""
from .state_parser import GoldStateParser, stateParser, checkStatoImpianto, checkZoneAperte
from .physical_map import GoldPhysicalMapParser
from .converter import GoldConverter
from .byte_utils import (
    hexstring_to_bcd,
    bcd2int,
    int2bcd,
    array_int_to_string,
    string_to_array_int,
    hexstring_to_array_int
)
from .device_stat_parser import (
    parse_radio_stat,
    parse_bus_stat,
    parse_filare_stat,
    parse_dev_stats,
    RadioDeviceStat,
    BusDeviceStat,
    FilareDeviceStat,
    get_device_type_name,
    RADIO_TYPE_RADIOCOMANDO,
    RADIO_TYPE_MOVIMENTO,
    RADIO_TYPE_CONTATTO,
    RADIO_TYPE_SIRENA,
    RADIO_TYPE_USCITA,
    RADIO_TYPE_TECNOLOGICO,
    RADIO_TYPE_NEBBIOGENO,
)

__all__ = [
    "GoldStateParser",
    "GoldPhysicalMapParser", 
    "GoldConverter",
    "stateParser",
    "checkStatoImpianto",
    "checkZoneAperte",
    "hexstring_to_bcd",
    "bcd2int",
    "int2bcd",
    "array_int_to_string",
    "string_to_array_int",
    "hexstring_to_array_int",
    # Device stat parser
    "parse_radio_stat",
    "parse_bus_stat",
    "parse_filare_stat",
    "parse_dev_stats",
    "RadioDeviceStat",
    "BusDeviceStat",
    "FilareDeviceStat",
    "get_device_type_name",
    "RADIO_TYPE_RADIOCOMANDO",
    "RADIO_TYPE_MOVIMENTO",
    "RADIO_TYPE_CONTATTO",
    "RADIO_TYPE_SIRENA",
    "RADIO_TYPE_USCITA",
    "RADIO_TYPE_TECNOLOGICO",
    "RADIO_TYPE_NEBBIOGENO",
]
