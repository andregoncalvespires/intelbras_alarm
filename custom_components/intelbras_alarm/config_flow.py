"""Config flow da integração Intelbras Alarm."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_CODE_REQUIRED_ARM,
    CONF_CODE_REQUIRED_DISARM,
    CONF_ENABLED_ZONES,
    CONF_MODEL,
    CONF_PARTITION_PASSWORDS,
    CONF_PASSWORD,
    CONF_RECEPTOR_IP_ENABLED,
    CONF_RECEPTOR_IP_PORT,
    DEFAULT_CODE_REQUIRED_ARM,
    DEFAULT_CODE_REQUIRED_DISARM,
    DEFAULT_ENABLED_ZONES_SPEC,
    DEFAULT_PORT,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_RECEPTOR_IP_ENABLED,
    DEFAULT_RECEPTOR_IP_PORT,
    DOMAIN,
    FAMILY_4010,
    InvalidZoneSpec,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    OPT_POLLING_INTERVAL,
    parse_zone_spec,
)
from .coordinator import async_detect_amt8000, async_detect_model
from .panel_client import PanelConnectionError
from .panel_client_amt8000 import Amt8000AuthError, PanelConnectionErrorAmt8000
from .protocol import NackError

_LOGGER = logging.getLogger(__name__)

# Campo do passo "user": marcar liga a autenticação/protocolo experimental
# da AMT 8000 em vez da sondagem automática entre 2018/1016/SMART/4010 (ver
# docstring de coordinator.async_detect_amt8000 para o motivo de não
# incluir esta família na sondagem automática).
CONF_AMT8000_MODE = "amt8000_mode"

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("port", default=DEFAULT_PORT): vol.Coerce(int),
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_AMT8000_MODE, default=False): bool,
        vol.Optional(CONF_CODE_REQUIRED_ARM, default=DEFAULT_CODE_REQUIRED_ARM): bool,
        vol.Optional(CONF_CODE_REQUIRED_DISARM, default=DEFAULT_CODE_REQUIRED_DISARM): bool,
        vol.Optional(CONF_ENABLED_ZONES, default=DEFAULT_ENABLED_ZONES_SPEC): str,
        vol.Optional(CONF_RECEPTOR_IP_ENABLED, default=DEFAULT_RECEPTOR_IP_ENABLED): bool,
        vol.Optional(CONF_RECEPTOR_IP_PORT, default=DEFAULT_RECEPTOR_IP_PORT): vol.Coerce(int),
    }
)

PARTITION_PASSWORD_FIELDS = {"A": "password_a", "B": "password_b", "C": "password_c", "D": "password_d"}

STEP_PARTITION_PASSWORDS_SCHEMA = vol.Schema(
    {
        vol.Optional(field, default=""): str
        for field in PARTITION_PASSWORD_FIELDS.values()
    }
)


async def _validate_and_detect(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    password = data[CONF_PASSWORD]
    if not (4 <= len(password) <= 6) or not password.isdigit():
        raise InvalidPassword

    # Só valida o FORMATO aqui (o modelo, e portanto o nº máximo de zonas,
    # ainda não foi detectado neste ponto do fluxo) — o intervalo de
    # 1..nº_zonas_do_modelo é reconferido depois, no coordinator, com o
    # padrão como fallback silencioso caso algo mude entre versões.
    # parse_zone_spec já levanta InvalidZoneSpec diretamente; deixamos
    # propagar para o chamador tratar.
    parse_zone_spec(data[CONF_ENABLED_ZONES])

    if data.get(CONF_AMT8000_MODE):
        # EXPERIMENTAL — ver coordinator.async_detect_amt8000. Não passa
        # pela sondagem automática 2018/4010 de propósito: são
        # protocolos de transporte incompatíveis (ver protocol_amt8000.py).
        model_key, model_name, family = await async_detect_amt8000(
            data["host"], data["port"], password
        )
    else:
        model_key, model_name, family = await async_detect_model(
            data["host"], data["port"], password
        )
    return {"model_key": model_key, "model_name": model_name, "family": family}


class IntelbrasAlarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Fluxo de configuração: host/porta/senha + detecção automática de modelo.

    Para a família 4010, um segundo passo opcional pergunta senhas
    específicas por partição (A/B/C/D) — a central 4010 suporta até 4
    partições, cada uma podendo ter sua própria senha cadastrada. Deixar em
    branco usa a senha principal para aquela partição.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(f"{user_input['host']}:{user_input['port']}")
            self._abort_if_unique_id_configured()

            try:
                detected = await _validate_and_detect(self.hass, user_input)
            except InvalidPassword:
                errors["base"] = "invalid_password"
            except InvalidZoneSpec:
                errors[CONF_ENABLED_ZONES] = "invalid_zone_spec"
            except PanelConnectionError:
                errors["base"] = "cannot_connect"
            except PanelConnectionErrorAmt8000:
                errors["base"] = "cannot_connect"
            except UpdateFailed:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Erro inesperado ao detectar a central")
                errors["base"] = "unknown"
            else:
                self._pending_data = {
                    "host": user_input["host"],
                    "port": user_input["port"],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_MODEL: detected["model_key"],
                    "model_name": detected["model_name"],
                    "family": detected["family"],
                    CONF_CODE_REQUIRED_ARM: user_input[CONF_CODE_REQUIRED_ARM],
                    CONF_CODE_REQUIRED_DISARM: user_input[CONF_CODE_REQUIRED_DISARM],
                    CONF_ENABLED_ZONES: user_input[CONF_ENABLED_ZONES],
                    CONF_RECEPTOR_IP_ENABLED: user_input[CONF_RECEPTOR_IP_ENABLED],
                    CONF_RECEPTOR_IP_PORT: user_input[CONF_RECEPTOR_IP_PORT],
                }
                if detected["family"] == FAMILY_4010:
                    return await self.async_step_partition_passwords()
                return self._create_entry()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_partition_passwords(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            partition_passwords: dict[str, str] = {}
            for partition, field in PARTITION_PASSWORD_FIELDS.items():
                value = user_input.get(field, "").strip()
                if not value:
                    continue
                if not (4 <= len(value) <= 6) or not value.isdigit():
                    errors[field] = "invalid_password"
                    continue
                partition_passwords[partition] = value

            if not errors:
                self._pending_data[CONF_PARTITION_PASSWORDS] = partition_passwords
                return self._create_entry()

        return self.async_show_form(
            step_id="partition_passwords",
            data_schema=STEP_PARTITION_PASSWORDS_SCHEMA,
            errors=errors,
        )

    def _create_entry(self) -> FlowResult:
        return self.async_create_entry(
            title=f"Intelbras {self._pending_data['model_name']} ({self._pending_data['host']})",
            data=self._pending_data,
            options={OPT_POLLING_INTERVAL: DEFAULT_POLLING_INTERVAL},
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> IntelbrasAlarmOptionsFlow:
        # Não passamos config_entry para o construtor de propósito — ver
        # docstring da classe. Fazer isso quebra com AttributeError/500 em
        # Home Assistant Core 2025.12+.
        return IntelbrasAlarmOptionsFlow()


class IntelbrasAlarmOptionsFlow(config_entries.OptionsFlow):
    """Permite ajustar senha, senhas por partição, opções de código e
    intervalo de polling **sem precisar remover e reconfigurar a
    integração do zero** — acessível pelo botão "Configurar" da própria
    integração (Ajustes → Dispositivos e Serviços → Intelbras Alarm →
    Configurar).

    Host/porta e o modelo detectado não são editáveis aqui de propósito
    (são praticamente fixos depois da instalação; trocar de central é
    melhor tratado removendo e reconfigurando do zero).

    IMPORTANTE: não armazenamos ``config_entry`` manualmente no
    ``__init__`` (`self.config_entry = config_entry`) — desde o Home
    Assistant Core 2025.12, isso é uma *property* somente-leitura da
    classe base (preenchida automaticamente pelo framework), e tentar
    atribuir a ela quebra com ``AttributeError`` / 500 Internal Server
    Error ("Server got itself in trouble") ao abrir a tela de
    configuração. `self.config_entry` já fica disponível sem precisarmos
    fazer nada — ver
    https://developers.home-assistant.io/blog/2024/11/12/options-flow/.
    """

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            if not (4 <= len(password) <= 6) or not password.isdigit():
                errors["base"] = "invalid_password"

            if not errors:
                # Confere a nova senha contra a central de verdade antes de
                # salvar — evita gravar uma senha errada e só descobrir no
                # próximo ciclo de polling, com a integração já quebrada.
                # IMPORTANTE: reaproveita a conexão TCP persistente já
                # aberta pelo coordinator, em vez de abrir uma segunda —
                # a central só aceita um cliente conectado por vez (mesmo
                # motivo do problema com o app AMT Remoto), então uma
                # segunda conexão simultânea para "só testar" falhava e
                # rejeitava até senhas corretas.
                coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id].coordinator
                try:
                    await coordinator.async_validate_password(password)
                except NackError:
                    errors["base"] = "password_rejected"
                except Amt8000AuthError:
                    errors["base"] = "password_rejected"
                except PanelConnectionError:
                    errors["base"] = "cannot_connect"
                except PanelConnectionErrorAmt8000:
                    errors["base"] = "cannot_connect"
                except UpdateFailed:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Erro inesperado ao validar a nova senha")
                    errors["base"] = "unknown"

            if not errors:
                self._pending_data = {
                    CONF_PASSWORD: password,
                    CONF_CODE_REQUIRED_ARM: user_input[CONF_CODE_REQUIRED_ARM],
                    CONF_CODE_REQUIRED_DISARM: user_input[CONF_CODE_REQUIRED_DISARM],
                    OPT_POLLING_INTERVAL: user_input[OPT_POLLING_INTERVAL],
                    CONF_RECEPTOR_IP_ENABLED: user_input[CONF_RECEPTOR_IP_ENABLED],
                    CONF_RECEPTOR_IP_PORT: user_input[CONF_RECEPTOR_IP_PORT],
                }
                if self.config_entry.data.get("family") == FAMILY_4010:
                    return await self.async_step_partition_passwords()
                return self._save()

        data = self.config_entry.data
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
                vol.Optional(
                    CONF_CODE_REQUIRED_ARM,
                    default=data.get(CONF_CODE_REQUIRED_ARM, DEFAULT_CODE_REQUIRED_ARM),
                ): bool,
                vol.Optional(
                    CONF_CODE_REQUIRED_DISARM,
                    default=data.get(CONF_CODE_REQUIRED_DISARM, DEFAULT_CODE_REQUIRED_DISARM),
                ): bool,
                # "Zonas habilitadas por padrão" (CONF_ENABLED_ZONES) NÃO
                # está aqui de propósito: entity_registry_enabled_default
                # só é lido pelo Home Assistant na primeira vez que cada
                # entidade é criada — como as zonas já foram todas criadas
                # na configuração inicial, mudar esse valor aqui não teria
                # nenhum efeito visível nas entidades existentes (o
                # Home Assistant não reaplica o "padrão" depois). Deixar
                # o campo aqui pareceria funcionar sem fazer nada de
                # verdade, então foi removido — continua disponível só na
                # configuração inicial, quando as entidades ainda não
                # existem.
                vol.Required(
                    OPT_POLLING_INTERVAL,
                    default=options.get(OPT_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL),
                ): vol.All(vol.Coerce(float), vol.Range(min=MIN_POLLING_INTERVAL, max=MAX_POLLING_INTERVAL)),
                # Diferente de CONF_ENABLED_ZONES acima, ligar/desligar o
                # Receptor IP aqui FUNCIONA de verdade: não depende de
                # nenhum "padrão de entidade" travado na criação — é só
                # iniciar ou parar um servidor toda vez que a integração
                # recarrega, o que já acontece automaticamente quando
                # qualquer opção muda.
                vol.Optional(
                    CONF_RECEPTOR_IP_ENABLED,
                    default=data.get(CONF_RECEPTOR_IP_ENABLED, DEFAULT_RECEPTOR_IP_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_RECEPTOR_IP_PORT,
                    default=data.get(CONF_RECEPTOR_IP_PORT, DEFAULT_RECEPTOR_IP_PORT),
                ): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def async_step_partition_passwords(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        current = self.config_entry.data.get(CONF_PARTITION_PASSWORDS, {})

        if user_input is not None:
            partition_passwords: dict[str, str] = {}
            for partition, field in PARTITION_PASSWORD_FIELDS.items():
                value = user_input.get(field, "").strip()
                if not value:
                    continue
                if not (4 <= len(value) <= 6) or not value.isdigit():
                    errors[field] = "invalid_password"
                    continue
                partition_passwords[partition] = value

            if not errors:
                self._pending_data[CONF_PARTITION_PASSWORDS] = partition_passwords
                return self._save()

        schema = vol.Schema(
            {
                vol.Optional(field, default=current.get(partition, "")): str
                for partition, field in PARTITION_PASSWORD_FIELDS.items()
            }
        )
        return self.async_show_form(
            step_id="partition_passwords", data_schema=schema, errors=errors
        )

    def _save(self) -> FlowResult:
        # Senha e opções de código vivem em entry.data (não em options) —
        # atualizamos ali diretamente. async_update_entry dispara o mesmo
        # listener de reload já usado para mudanças de options, então a
        # integração recarrega sozinha com os novos valores, sem exigir
        # remover/adicionar de novo. "Zonas habilitadas por padrão" fica
        # de fora de propósito — ver comentário em async_step_init.
        new_data = dict(self.config_entry.data)
        new_data[CONF_PASSWORD] = self._pending_data[CONF_PASSWORD]
        new_data[CONF_CODE_REQUIRED_ARM] = self._pending_data[CONF_CODE_REQUIRED_ARM]
        new_data[CONF_CODE_REQUIRED_DISARM] = self._pending_data[CONF_CODE_REQUIRED_DISARM]
        new_data[CONF_RECEPTOR_IP_ENABLED] = self._pending_data[CONF_RECEPTOR_IP_ENABLED]
        new_data[CONF_RECEPTOR_IP_PORT] = self._pending_data[CONF_RECEPTOR_IP_PORT]
        if CONF_PARTITION_PASSWORDS in self._pending_data:
            new_data[CONF_PARTITION_PASSWORDS] = self._pending_data[CONF_PARTITION_PASSWORDS]
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        return self.async_create_entry(
            title="", data={OPT_POLLING_INTERVAL: self._pending_data[OPT_POLLING_INTERVAL]}
        )


class InvalidPassword(Exception):
    """Senha fora do padrão aceito pela central (4 a 6 dígitos)."""
