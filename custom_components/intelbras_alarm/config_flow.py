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
    CONF_MODEL,
    CONF_PARTITION_PASSWORDS,
    CONF_PASSWORD,
    DEFAULT_CODE_REQUIRED_ARM,
    DEFAULT_CODE_REQUIRED_DISARM,
    DEFAULT_PORT,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    FAMILY_4010,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    OPT_POLLING_INTERVAL,
)
from .coordinator import async_detect_model
from .panel_client import PanelConnectionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("port", default=DEFAULT_PORT): vol.Coerce(int),
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_CODE_REQUIRED_ARM, default=DEFAULT_CODE_REQUIRED_ARM): bool,
        vol.Optional(CONF_CODE_REQUIRED_DISARM, default=DEFAULT_CODE_REQUIRED_DISARM): bool,
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
            except PanelConnectionError:
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
        return IntelbrasAlarmOptionsFlow(config_entry)


class IntelbrasAlarmOptionsFlow(config_entries.OptionsFlow):
    """Permite ajustar o intervalo de polling após a configuração inicial."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            OPT_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(OPT_POLLING_INTERVAL, default=current): vol.All(
                    vol.Coerce(float), vol.Range(min=MIN_POLLING_INTERVAL, max=MAX_POLLING_INTERVAL)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class InvalidPassword(Exception):
    """Senha fora do padrão aceito pela central (4 a 6 dígitos)."""
