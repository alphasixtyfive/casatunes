"""Config flow for CasaTunes."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from pycasatunes import CasaTunes
from pycasatunes.exceptions import CasaException
import async_timeout
import voluptuous as vol

from homeassistant.components.ssdp import ATTR_SSDP_LOCATION
from homeassistant.helpers.service_info.ssdp import ATTR_UPNP_FRIENDLY_NAME
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .const import DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})

async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate connectivity and fetch system info."""
    session = async_get_clientsession(hass)
    casa = CasaTunes(session, data[CONF_HOST])
    # Use fetch() instead of deprecated get_system()
    async with async_timeout.timeout(10):
        await casa.fetch()
    system = casa.system
    return {
        "title": system.AppName,
        "mac_address": format_mac(system.MACAddress),
    }

class CasaTunesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a CasaTunes config flow."""
    VERSION = 1

    def __init__(self):
        self.discovery_info: dict[str, str] = {}

    @callback
    def _show_setup_form(self, errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors or {},
        )

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        if user_input is None:
            return self._show_setup_form()

        errors: dict[str, str] = {}
        try:
            info = await validate_input(self.hass, user_input)
        except CasaException:
            _LOGGER.debug("Unable to connect to CasaTunes", exc_info=True)
            errors["base"] = "cannot_connect"
            return self._show_setup_form(errors)
        except Exception:
            _LOGGER.exception("Unexpected error connecting to CasaTunes")
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(info["mac_address"])
        self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})

        return self.async_create_entry(
            title=info["title"],
            data={CONF_HOST: user_input[CONF_HOST]},
        )

    async def async_step_ssdp(
        self, discovery_info: DiscoveryInfoType
    ) -> FlowResult:
        """Handle a flow initiated by SSDP discovery."""
        host = urlparse(discovery_info[ATTR_SSDP_LOCATION]).hostname
        name = discovery_info[ATTR_UPNP_FRIENDLY_NAME]
        try:
            session = async_get_clientsession(self.hass)
            casa = CasaTunes(session, host)
            async with async_timeout.timeout(10):
                await casa.fetch()
            mac = casa.system.MACAddress
        except CasaException:
            return self.async_abort(reason="cannot_connect")
        except Exception:
            _LOGGER.exception("Unexpected error fetching MAC from CasaTunes")
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(format_mac(mac))
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self.context["title_placeholders"] = {"name": name}
        self.discovery_info = {CONF_HOST: host, CONF_NAME: name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Confirm discovery and create entry."""
        if user_input is not None:
            return self.async_create_entry(
                title=self.discovery_info[CONF_NAME],
                data={CONF_HOST: self.discovery_info[CONF_HOST]},
            )

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self.discovery_info[CONF_NAME]},
        )
