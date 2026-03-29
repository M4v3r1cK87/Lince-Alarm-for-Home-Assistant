"""Config flow for Lince Alarm integration."""
from __future__ import annotations
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.helpers.selector import (
    TextSelector, TextSelectorConfig, TextSelectorType,
    SelectSelector, SelectSelectorConfig, SelectOptionDict, SelectSelectorMode,
    BooleanSelector,
)
from .const import DOMAIN
from .common.api import CommonAPI
from .factory import ComponentFactory
from .euronet.const import (
    # Configurazione connessione
    CONF_LOCAL_MODE,
    CONF_HOST,
    CONF_PORT,
    CONF_PASSWORD,
    CONF_INSTALLER_CODE,
    DEFAULT_LOCAL_USERNAME,
    DEFAULT_LOCAL_PORT,
    # Zone
    CONF_NUM_ZONE_FILARI,
    CONF_NUM_ZONE_RADIO,
    MAX_FILARI as LOCAL_MAX_FILARI,
    MAX_RADIO as LOCAL_MAX_RADIO,
    DEFAULT_FILARI as LOCAL_DEFAULT_FILARI,
    DEFAULT_RADIO as LOCAL_DEFAULT_RADIO,
    # ARM profiles
    CONF_ARM_PROFILES,
    PROGRAMS as LOCAL_PROGRAMS,
    PROGRAM_BITS as LOCAL_PROGRAM_BITS,
    DEFAULT_ARM_PROFILES as LOCAL_DEFAULT_ARM_PROFILES,
    # Polling
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL_MS,
    POLLING_INTERVAL_OPTIONS,
)
from .gold.const import CONF_USER_CODE

_LOGGER = logging.getLogger(__name__)


class LinceGoldCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow: selezione modalità cloud o locale."""
    VERSION = 2  # Incrementato per nuova struttura dati

    def __init__(self):
        """Inizializza il config flow."""
        self._local_data: dict = {}  # Dati temporanei per modalità locale

    async def async_step_user(self, user_input=None):
        """Step iniziale: scegli modalità cloud o locale."""
        errors = {}
        
        if user_input is not None:
            # Salva la scelta e vai allo step appropriato
            if user_input.get(CONF_LOCAL_MODE, False):
                return await self.async_step_local_login()
            else:
                return await self.async_step_cloud_login()

        schema = vol.Schema({
            vol.Required(CONF_LOCAL_MODE, default=False): BooleanSelector(),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_cloud_login(self, user_input=None):
        """Step login cloud (comportamento originale)."""
        errors = {}
        
        if user_input is not None:
            api = CommonAPI(self.hass)
            try:
                await api.login(user_input["email"], user_input["password"])
                if not api.token:
                    errors["base"] = "auth_failed"
                else:
                    return self.async_create_entry(
                        title=f"Lince Cloud ({user_input['email']})",
                        data={
                            CONF_LOCAL_MODE: False,
                            "email": user_input["email"], 
                            "password": user_input["password"],
                        },
                    )
            except Exception as e:
                _LOGGER.error(f"Login cloud fallito: {e}")
                errors["base"] = "auth_failed"

        schema = vol.Schema({
            vol.Required("email"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
            ),
            vol.Required("password"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="password")
            ),
        })
        return self.async_show_form(step_id="cloud_login", data_schema=schema, errors=errors)

    async def async_step_local_login(self, user_input=None):
        """Step login locale (nuova modalità)."""
        errors = {}
        
        if user_input is not None:
            host = user_input.get(CONF_HOST, "").strip()
            port = user_input.get(CONF_PORT, DEFAULT_LOCAL_PORT)
            password = user_input.get(CONF_PASSWORD, "")
            installer_code = user_input.get(CONF_INSTALLER_CODE, "").strip()
            
            # Validazione base
            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                # Testa la connessione (username è sempre "admin")
                try:
                    from .euronet import EuroNetClient
                    client = EuroNetClient(
                        host=host,
                        port=port,
                        username=DEFAULT_LOCAL_USERNAME,
                        password=password,
                    )
                    # Test connessione in executor per non bloccare
                    connected = await self.hass.async_add_executor_job(
                        client.test_connection
                    )
                    if not connected:
                        errors["base"] = "connection_failed"
                    else:
                        # Salva i dati e vai alla configurazione zone/profili
                        self._local_data = {
                            CONF_LOCAL_MODE: True,
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_PASSWORD: password,
                            CONF_INSTALLER_CODE: installer_code,
                        }
                        return await self.async_step_local_config()
                except Exception as e:
                    _LOGGER.error(f"Connessione locale fallita: {e}")
                    errors["base"] = "connection_failed"

        schema = vol.Schema({
            vol.Required(CONF_HOST): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Optional(CONF_PORT, default=DEFAULT_LOCAL_PORT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="password")
            ),
            vol.Optional(CONF_INSTALLER_CODE): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        })
        return self.async_show_form(step_id="local_login", data_schema=schema, errors=errors)

    async def async_step_local_config(self, user_input=None):
        """Step configurazione zone e profili ARM per modalità locale."""
        errors = {}
        
        # Opzioni per i programmi
        prog_options = [
            SelectOptionDict(value=prog, label=prog.upper())
            for prog in LOCAL_PROGRAMS
        ]
        
        # Opzioni polling interval (converti ms in label leggibili)
        polling_options = []
        for ms_value in POLLING_INTERVAL_OPTIONS:
            if ms_value < 1000:
                label = f"{ms_value}ms"
            else:
                label = f"{ms_value // 1000} secondo" if ms_value == 1000 else f"{ms_value // 1000} secondi"
            polling_options.append(SelectOptionDict(value=str(ms_value), label=label))
        
        # Default values
        defaults = {
            CONF_NUM_ZONE_FILARI: LOCAL_DEFAULT_FILARI,
            CONF_NUM_ZONE_RADIO: LOCAL_DEFAULT_RADIO,
            CONF_POLLING_INTERVAL: DEFAULT_POLLING_INTERVAL_MS,
            "home": LOCAL_DEFAULT_ARM_PROFILES.get("home", []),
            "away": LOCAL_DEFAULT_ARM_PROFILES.get("away", []),
            "night": LOCAL_DEFAULT_ARM_PROFILES.get("night", []),
            "vacation": LOCAL_DEFAULT_ARM_PROFILES.get("vacation", []),
        }
        
        if user_input is not None:
            # Parse numerici
            try:
                num_filari = int(user_input.get(CONF_NUM_ZONE_FILARI, LOCAL_DEFAULT_FILARI))
                num_radio = int(user_input.get(CONF_NUM_ZONE_RADIO, LOCAL_DEFAULT_RADIO))
            except (ValueError, TypeError):
                num_filari, num_radio = LOCAL_DEFAULT_FILARI, LOCAL_DEFAULT_RADIO
            
            # Clamp ai massimi
            num_filari = min(max(0, num_filari), LOCAL_MAX_FILARI)
            num_radio = min(max(0, num_radio), LOCAL_MAX_RADIO)
            
            # Parse polling interval
            polling_interval = user_input.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL_MS)
            if isinstance(polling_interval, str):
                polling_interval = int(polling_interval)
            
            # Profili ARM
            arm_profiles = {
                "home": user_input.get("home", []) or [],
                "away": user_input.get("away", []) or [],
                "night": user_input.get("night", []) or [],
                "vacation": user_input.get("vacation", []) or [],
            }
            
            # Validazione: profili con mask unica
            def to_mask(progs):
                m = 0
                for p in progs or []:
                    m |= LOCAL_PROGRAM_BITS.get(p, 0)
                return m
            
            masks = {k: to_mask(v) for k, v in arm_profiles.items()}
            
            # Conta duplicati (escludo mask=0)
            count_by_mask = {}
            for mode, m in masks.items():
                if m != 0:
                    count_by_mask[m] = count_by_mask.get(m, 0) + 1
            
            dup_modes = [mode for mode, m in masks.items() if m != 0 and count_by_mask.get(m, 0) > 1]
            
            if dup_modes:
                errors["base"] = "duplicate_profiles"
                for mode in dup_modes:
                    errors[mode] = "duplicate_profile"
            else:
                # Tutto OK, crea l'entry
                host = self._local_data.get(CONF_HOST, "")
                return self.async_create_entry(
                    title=f"Modulo EuroNET ({host})",
                    data=self._local_data,
                    options={
                        CONF_NUM_ZONE_FILARI: num_filari,
                        CONF_NUM_ZONE_RADIO: num_radio,
                        CONF_ARM_PROFILES: arm_profiles,
                        CONF_POLLING_INTERVAL: polling_interval,
                    },
                )
        
        # Schema del form
        schema = vol.Schema({
            vol.Required(CONF_NUM_ZONE_FILARI, default=defaults[CONF_NUM_ZONE_FILARI]): 
                vol.All(vol.Coerce(int), vol.Range(min=0, max=LOCAL_MAX_FILARI)),
            vol.Required(CONF_NUM_ZONE_RADIO, default=defaults[CONF_NUM_ZONE_RADIO]): 
                vol.All(vol.Coerce(int), vol.Range(min=0, max=LOCAL_MAX_RADIO)),
            vol.Required(CONF_POLLING_INTERVAL, default=str(defaults[CONF_POLLING_INTERVAL])): SelectSelector(
                SelectSelectorConfig(
                    options=polling_options,
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("home", default=defaults["home"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("away", default=defaults["away"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("night", default=defaults["night"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("vacation", default=defaults["vacation"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
        })
        
        return self.async_show_form(
            step_id="local_config", 
            data_schema=schema, 
            errors=errors,
            description_placeholders={
                "max_filari": LOCAL_MAX_FILARI,
                "max_radio": LOCAL_MAX_RADIO,
            },
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return LinceGoldCloudOptionsFlow(config_entry)
    
    async def async_step_reauth(self, user_input=None):
        """Handle reauth when token/credentials no longer valid."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
        
        if user_input is None:
            # Mostra form con email pre-compilata
            schema = vol.Schema({
                vol.Required("email", default=entry.data.get("email", "")): str,
                vol.Required("password"): str,
            })
            return self.async_show_form(step_id="reauth", data_schema=schema, errors=errors)

        # Verifica nuove credenziali
        api = CommonAPI(self.hass)  # ✅ CommonAPI esiste
        try:
            await api.login(user_input["email"], user_input["password"])
            if not api.token:
                raise Exception("No token received")
        except Exception as e:
            _LOGGER.error(f"Reauth fallito: {e}")
            errors["base"] = "auth_failed"
            schema = vol.Schema({
                vol.Required("email", default=user_input["email"]): str,
                vol.Required("password"): str,
            })
            return self.async_show_form(step_id="reauth", data_schema=schema, errors=errors)

        # Credenziali OK -> aggiorna il config_entry
        data = dict(entry.data)
        data["email"] = user_input["email"]
        data["password"] = user_input["password"]
        self.hass.config_entries.async_update_entry(entry, data=data)

        # Ricarica l'integrazione
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason="reauth_successful")


class LinceGoldCloudOptionsFlow(OptionsFlowWithReload):
    """Options Flow per-centrale con supporto multi-brand."""

    def __init__(self, entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self._entry = entry
        self._systems: list[dict] = []
        self._current_sid: int | None = None
        self._current_brand: str = "lince-europlus"

    @staticmethod
    def _program_display_name_from_access(system: dict | None, code: str) -> str:
        """Costruisce il label 'G1 - Porta' usando system['access_data']."""
        upper = code.upper()
        access = (system or {}).get("access_data", {}) or {}
        custom = (access.get(code) or "").strip()
        return f"{upper} - {custom}" if custom else upper

    def _get_system_by_sid(self, sid: int) -> dict | None:
        """Trova un sistema per ID."""
        for s in self._systems or []:
            if s.get("id") == sid:
                return s
        return None

    async def async_step_init(self, user_input=None):
        """Step iniziale: selezione della centrale o configurazione locale."""
        errors = {}
        
        # Controlla se siamo in modalità locale
        if self._entry.data.get(CONF_LOCAL_MODE, False):
            # Modalità LOCALE: vai direttamente alla configurazione
            return await self.async_step_local_options()
        
        # Modalità CLOUD: carica lista centrali
        email = self._entry.data.get("email")
        password = self._entry.data.get("password")
        api = CommonAPI(self.hass)  # ✅ CommonAPI esiste in common/api.py
        
        try:
            await api.login(email, password)
            self._systems = await api.fetch_systems() or []
            
            # Recupera access_data e determina brand per ogni sistema
            for s in self._systems:
                sid = s["id"]
                try:
                    s["access_data"] = await api.fetch_system_access(sid)
                except Exception as e:
                    _LOGGER.debug(f"Impossibile caricare access_data per sistema {sid}: {e}")
                    s["access_data"] = {}
                
                # Determina e salva il brand
                s["_brand"] = ComponentFactory.get_brand_from_system(s)
                
        except Exception as e:
            _LOGGER.debug("Impossibile caricare centrali in Options: %s", e)
            # Fallback dalle opzioni salvate
            systems_config = self._entry.options.get("systems_config", {})
            self._systems = []
            for sid_str in systems_config.keys():
                try:
                    sid = int(sid_str)
                    config = systems_config[sid_str]
                    self._systems.append({
                        "id": sid, 
                        "name": f"Centrale {sid}",
                        "_brand": config.get("brand", "lince-europlus")
                    })
                except ValueError:
                    continue

        # Crea opzioni per il selettore
        options = []
        for s in self._systems:
            sid = s["id"]
            brand = s.get("_brand", "lince-europlus")
            display = f"{s.get('name') or s.get('nome') or f'Centrale {sid}'}"
            if s.get('id_centrale'):
                display += f" - {s.get('id_centrale')}"
            display += f" [{brand}]"
            options.append(SelectOptionDict(value=str(sid), label=display))

        if not options:
            # Nessuna centrale configurabile
            return self.async_create_entry(title="", data=self._entry.options)

        schema = vol.Schema({
            vol.Required("system"): SelectSelector(
                SelectSelectorConfig(
                    options=options, 
                    multiple=False, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            )
        })

        if user_input is not None:
            self._current_sid = int(user_input["system"])
            # Determina il brand del sistema selezionato
            system = self._get_system_by_sid(self._current_sid)
            if system:
                self._current_brand = system.get("_brand", "lince-europlus")
            return await self.async_step_edit_details()

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def _load_name_for_sid(self, sid: int) -> str:
        """Ritorna 'Nome - id_centrale' per il sistema."""
        name = f"Centrale {sid}"
        cached = self._get_system_by_sid(sid)
        if cached:
            base_name = cached.get('name') or cached.get('nome') or name
            if cached.get('id_centrale'):
                return f"{base_name} - {cached.get('id_centrale')}"
            return base_name
            
        # Rifetch solo se necessario
        email = self._entry.data.get("email")
        password = self._entry.data.get("password")
        try:
            api = CommonAPI(self.hass)  # ✅ CommonAPI esiste
            await api.login(email, password)
            systems = await api.fetch_systems() or []
            for s in systems:
                if s["id"] == sid:
                    base_name = s.get('name') or s.get('nome') or name
                    if s.get('id_centrale'):
                        return f"{base_name} - {s.get('id_centrale')}"
                    return base_name
        except Exception:
            pass
        return name

    async def async_step_edit_details(self, user_input=None):
        """Step per configurare dettagli della centrale (zone e profili)."""
        errors: dict[str, str] = {}

        if not self._current_sid:
            return await self.async_step_init()

        sid = self._current_sid
        sid_str = str(sid)
        name = await self._load_name_for_sid(sid)
        system = self._get_system_by_sid(sid)
        
        # Determina il brand e ottieni le costanti appropriate
        brand = self._current_brand
        constants = ComponentFactory.get_constants(brand)
        
        # Estrai costanti brand-specific
        MAX_FILARI_BRAND = constants["MAX_FILARI"]
        MAX_RADIO_BRAND = constants["MAX_RADIO"]
        DEFAULT_FILARI_BRAND = constants["DEFAULT_FILARI"]
        DEFAULT_RADIO_BRAND = constants["DEFAULT_RADIO"]
        SUPPORTS_GEXT = constants["SUPPORTS_GEXT"]
        PROGRAMS = constants["PROGRAMS"]

        _LOGGER.debug(f"Configurazione per centrale {sid} (brand: {brand}): "
                     f"MAX_FILARI={MAX_FILARI_BRAND}, MAX_RADIO={MAX_RADIO_BRAND}, "
                     f"SUPPORTS_GEXT={SUPPORTS_GEXT}, PROGRAMS={PROGRAMS}")

        # Carica configurazioni esistenti
        systems_config = dict(self._entry.options.get("systems_config", {}))
        arm_profiles = dict(self._entry.options.get("arm_profiles", {}))

        # Opzioni dinamiche per i programmi in base al brand
        prog_options = []
        for prog in PROGRAMS:
            prog_options.append(
                SelectOptionDict(
                    value=prog,
                    label=self._program_display_name_from_access(system, prog)
                )
            )

        # Defaults correnti da options salvate
        cfg = systems_config.get(sid_str, {})
        prof = arm_profiles.get(sid_str, {
            "home": [], "away": [], "night": [], "vacation": []
        })
        
        defaults = {
            "num_filari": int(cfg.get("num_filari", DEFAULT_FILARI_BRAND)),
            "num_radio": int(cfg.get("num_radio", DEFAULT_RADIO_BRAND)),
            "home": list(prof.get("home", [])),
            "away": list(prof.get("away", [])),
            "night": list(prof.get("night", [])),
            "vacation": list(prof.get("vacation", [])),
            CONF_USER_CODE: cfg.get(CONF_USER_CODE, ""),  # Codice utente Gold
        }

        # Filtra profili per rimuovere programmi non supportati
        for profile in ["home", "away", "night", "vacation"]:
            defaults[profile] = [p for p in defaults[profile] if p in PROGRAMS]

        # Schema base con limiti brand-specific
        schema_fields = {
            vol.Required("num_filari", default=defaults["num_filari"]): 
                vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_FILARI_BRAND)),
            vol.Required("num_radio", default=defaults["num_radio"]): 
                vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_RADIO_BRAND)),
        }
        
        # Aggiungi campo codice utente solo per centrali Gold
        if brand == "lince-gold":
            schema_fields[vol.Optional(CONF_USER_CODE, default=defaults[CONF_USER_CODE])] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
        
        # Aggiungi campi profili ARM
        schema_fields.update({
            vol.Optional("home", default=defaults["home"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("away", default=defaults["away"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("night", default=defaults["night"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("vacation", default=defaults["vacation"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
        })
        
        base_schema = vol.Schema(schema_fields)

        # Se l'utente ha inviato il form, valida e salva
        if user_input is not None:
            # Parse sicuro dei numerici
            try:
                nfil = int(user_input.get("num_filari", DEFAULT_FILARI_BRAND))
                nrad = int(user_input.get("num_radio", DEFAULT_RADIO_BRAND))
            except Exception:
                nfil, nrad = DEFAULT_FILARI_BRAND, DEFAULT_RADIO_BRAND

            # Clamp ai massimi brand-specific
            nfil = min(max(0, nfil), MAX_FILARI_BRAND)
            nrad = min(max(0, nrad), MAX_RADIO_BRAND)

            # Multi-select -> liste
            selected = {
                "home": user_input.get("home", []) or [],
                "away": user_input.get("away", []) or [],
                "night": user_input.get("night", []) or [],
                "vacation": user_input.get("vacation", []) or [],
            }

            # Validazione "mask uniche" tra profili
            # Costruisci bitmask dinamicamente in base ai programmi supportati
            PROGRAM_BITS = constants.get("PROGRAM_BITS", {})

            def to_mask(progs: list[str]) -> int:
                m = 0
                for x in progs or []:
                    m |= PROGRAM_BITS.get(x, 0)
                return m

            masks = {
                "home": to_mask(selected["home"]),
                "away": to_mask(selected["away"]),
                "night": to_mask(selected["night"]),
                "vacation": to_mask(selected["vacation"]),
            }

            # Conta duplicati
            count_by_mask: dict[int, int] = {}
            for mode, m in masks.items():
                if m != 0:
                    count_by_mask[m] = count_by_mask.get(m, 0) + 1

            # Modalità duplicate
            dup_modes = [mode for mode, m in masks.items() 
                        if m != 0 and count_by_mask.get(m, 0) > 1]
            
            if dup_modes:
                # Errori per duplicati
                errors["base"] = "duplicate_profiles"
                for mode in dup_modes:
                    errors[mode] = "duplicate_profile"

                # Mantieni valori con suggested
                suggested = {
                    "num_filari": nfil,
                    "num_radio": nrad,
                    "home": selected["home"],
                    "away": selected["away"],
                    "night": selected["night"],
                    "vacation": selected["vacation"],
                }
                # Aggiungi user_code se Gold
                if brand == "lince-gold":
                    suggested[CONF_USER_CODE] = user_input.get(CONF_USER_CODE, "")
                    
                schema_with_suggested = self.add_suggested_values_to_schema(base_schema, suggested)
                return self.async_show_form(
                    step_id="edit_details",
                    data_schema=schema_with_suggested,
                    errors=errors,
                    description_placeholders={
                        "system_name": name, 
                        "system_id": sid,
                        "brand": brand,
                        "max_filari": MAX_FILARI_BRAND,
                        "max_radio": MAX_RADIO_BRAND
                    },
                )

            # Nessun duplicato -> salva configurazione
            system_cfg = {
                "num_filari": nfil, 
                "num_radio": nrad,
                "brand": brand  # Salva anche il brand nella config
            }
            
            # Gestisci codice utente Gold per ottenere nomi zone
            if brand == "lince-gold":
                user_code = user_input.get(CONF_USER_CODE, "").strip()
                if user_code:
                    system_cfg[CONF_USER_CODE] = user_code
                    
                    # Prova a ottenere i nomi delle zone dall'API
                    try:
                        # Ottieni id_centrale dal sistema
                        id_centrale = system.get("id_centrale") if system else None
                        if id_centrale:
                            from .gold.api import GoldAPI
                            email = self._entry.data.get("email")
                            password = self._entry.data.get("password")
                            gold_api = GoldAPI(self.hass, email, password)
                            await gold_api.login()
                            
                            login_data = await gold_api.gold_login_with_code(id_centrale, user_code)
                            if login_data:
                                zone_names = gold_api.parse_zone_names_from_login(login_data)
                                system_cfg["zone_names"] = zone_names
                                _LOGGER.info(f"Nomi zone Gold caricati per centrale {sid}: "
                                           f"filari={len(zone_names.get('filari', {}))}, "
                                           f"radio={len(zone_names.get('radio', {}))}")
                            else:
                                _LOGGER.warning(f"Login Gold con codice fallita per centrale {sid}")
                        else:
                            _LOGGER.warning(f"id_centrale non trovato per sistema Gold {sid}")
                    except Exception as e:
                        _LOGGER.error(f"Errore durante caricamento nomi zone Gold: {e}")
                else:
                    # Rimuovi nomi zone se codice rimosso
                    system_cfg.pop(CONF_USER_CODE, None)
                    system_cfg.pop("zone_names", None)
            
            systems_config[sid_str] = system_cfg
            arm_profiles[sid_str] = selected
            
            _LOGGER.debug(f"Salvando config per centrale {sid} (brand: {brand}): "
                         f"filari={nfil}, radio={nrad}")
            _LOGGER.debug(f"Profili ARM per {sid}: {selected}")

            new_options = dict(self._entry.options)
            new_options["systems_config"] = systems_config
            new_options["arm_profiles"] = arm_profiles
            
            return self.async_create_entry(title="", data=new_options)

        # Primo rendering della form
        return self.async_show_form(
            step_id="edit_details",
            data_schema=base_schema,
            errors=errors,
            description_placeholders={
                "system_name": name, 
                "system_id": sid,
                "brand": brand,
                "max_filari": MAX_FILARI_BRAND,
                "max_radio": MAX_RADIO_BRAND
            },
        )

    async def async_step_local_options(self, user_input=None):
        """Step configurazione opzioni per modalità locale."""
        errors = {}
        
        # Opzioni per i programmi
        prog_options = [
            SelectOptionDict(value=prog, label=prog.upper())
            for prog in LOCAL_PROGRAMS
        ]
        
        # Carica valori correnti dalle options
        current_options = self._entry.options or {}
        arm_profiles = current_options.get(CONF_ARM_PROFILES, LOCAL_DEFAULT_ARM_PROFILES)
        
        defaults = {
            CONF_POLLING_INTERVAL: current_options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL_MS),
            CONF_NUM_ZONE_FILARI: current_options.get(CONF_NUM_ZONE_FILARI, LOCAL_DEFAULT_FILARI),
            CONF_NUM_ZONE_RADIO: current_options.get(CONF_NUM_ZONE_RADIO, LOCAL_DEFAULT_RADIO),
            "home": arm_profiles.get("home", LOCAL_DEFAULT_ARM_PROFILES.get("home", [])),
            "away": arm_profiles.get("away", LOCAL_DEFAULT_ARM_PROFILES.get("away", [])),
            "night": arm_profiles.get("night", LOCAL_DEFAULT_ARM_PROFILES.get("night", [])),
            "vacation": arm_profiles.get("vacation", LOCAL_DEFAULT_ARM_PROFILES.get("vacation", [])),
        }
        
        if user_input is not None:
            # Parse polling interval
            polling_interval = user_input.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL_MS)
            if isinstance(polling_interval, str):
                polling_interval = int(polling_interval)
            
            # Parse numerici zone
            try:
                num_filari = int(user_input.get(CONF_NUM_ZONE_FILARI, LOCAL_DEFAULT_FILARI))
                num_radio = int(user_input.get(CONF_NUM_ZONE_RADIO, LOCAL_DEFAULT_RADIO))
            except (ValueError, TypeError):
                num_filari, num_radio = LOCAL_DEFAULT_FILARI, LOCAL_DEFAULT_RADIO
            
            # Clamp ai massimi
            num_filari = min(max(0, num_filari), LOCAL_MAX_FILARI)
            num_radio = min(max(0, num_radio), LOCAL_MAX_RADIO)
            
            # Profili ARM
            new_arm_profiles = {
                "home": user_input.get("home", []) or [],
                "away": user_input.get("away", []) or [],
                "night": user_input.get("night", []) or [],
                "vacation": user_input.get("vacation", []) or [],
            }
            
            # Validazione: profili con mask unica
            def to_mask(progs):
                m = 0
                for p in progs or []:
                    m |= LOCAL_PROGRAM_BITS.get(p, 0)
                return m
            
            masks = {k: to_mask(v) for k, v in new_arm_profiles.items()}
            
            # Conta duplicati (escludo mask=0)
            count_by_mask = {}
            for mode, m in masks.items():
                if m != 0:
                    count_by_mask[m] = count_by_mask.get(m, 0) + 1
            
            dup_modes = [mode for mode, m in masks.items() if m != 0 and count_by_mask.get(m, 0) > 1]
            
            if dup_modes:
                errors["base"] = "duplicate_profiles"
                for mode in dup_modes:
                    errors[mode] = "duplicate_profile"
            else:
                # Gestisci password e installer_code
                # Se vuoti, mantieni i valori esistenti; altrimenti aggiorna
                new_password = user_input.get(CONF_PASSWORD, "").strip()
                new_installer_code = user_input.get(CONF_INSTALLER_CODE, "").strip()
                
                current_data = dict(self._entry.data)
                data_changed = False
                password_changed = False
                installer_code_changed = False
                
                if new_password:
                    old_password = self._entry.data.get(CONF_PASSWORD, "")
                    if new_password != old_password:
                        password_changed = True
                    current_data[CONF_PASSWORD] = new_password
                    data_changed = True
                
                if new_installer_code:
                    # Verifica se il codice installatore è cambiato
                    old_installer_code = self._entry.data.get(CONF_INSTALLER_CODE, "")
                    if new_installer_code != old_installer_code:
                        installer_code_changed = True
                    current_data[CONF_INSTALLER_CODE] = new_installer_code
                    data_changed = True
                
                # Aggiorna config_entry.data se ci sono modifiche alle credenziali
                if data_changed:
                    self.hass.config_entries.async_update_entry(
                        self._entry, data=current_data
                    )
                
                # Se password o codice installatore cambiati, forza reload dell'integrazione
                if password_changed or installer_code_changed:
                    reason = []
                    if password_changed:
                        reason.append("password")
                    if installer_code_changed:
                        reason.append("codice installatore")
                    _LOGGER.info("Credenziali modificate (%s) - reload integrazione", ", ".join(reason))
                    # Schedula il reload dopo che l'options flow è completato
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(self._entry.entry_id)
                    )
                
                # Salva le nuove opzioni
                new_options = {
                    CONF_POLLING_INTERVAL: polling_interval,
                    CONF_NUM_ZONE_FILARI: num_filari,
                    CONF_NUM_ZONE_RADIO: num_radio,
                    CONF_ARM_PROFILES: new_arm_profiles,
                }
                return self.async_create_entry(title="", data=new_options)
        
        # Opzioni per polling interval (converti ms in label leggibili)
        polling_options = []
        for ms in POLLING_INTERVAL_OPTIONS:
            if ms < 1000:
                label = f"{ms}ms"
            elif ms < 60000:
                label = f"{ms // 1000}s"
            else:
                label = f"{ms // 60000}min"
            polling_options.append(SelectOptionDict(value=str(ms), label=label))
        
        # Schema del form - password e codice mostrati come opzionali (vuoto = non modificare)
        schema = vol.Schema({
            vol.Optional(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_INSTALLER_CODE): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_POLLING_INTERVAL, default=str(defaults[CONF_POLLING_INTERVAL])): SelectSelector(
                SelectSelectorConfig(
                    options=polling_options,
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required(CONF_NUM_ZONE_FILARI, default=defaults[CONF_NUM_ZONE_FILARI]): 
                vol.All(vol.Coerce(int), vol.Range(min=0, max=LOCAL_MAX_FILARI)),
            vol.Required(CONF_NUM_ZONE_RADIO, default=defaults[CONF_NUM_ZONE_RADIO]): 
                vol.All(vol.Coerce(int), vol.Range(min=0, max=LOCAL_MAX_RADIO)),
            vol.Optional("home", default=defaults["home"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("away", default=defaults["away"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("night", default=defaults["night"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional("vacation", default=defaults["vacation"]): SelectSelector(
                SelectSelectorConfig(
                    options=prog_options, 
                    multiple=True, 
                    mode=SelectSelectorMode.DROPDOWN
                )
            ),
        })
        
        host = self._entry.data.get(CONF_HOST, "Locale")
        return self.async_show_form(
            step_id="local_options", 
            data_schema=schema, 
            errors=errors,
            description_placeholders={
                "host": host,
                "max_filari": LOCAL_MAX_FILARI,
                "max_radio": LOCAL_MAX_RADIO,
            },
        )
    