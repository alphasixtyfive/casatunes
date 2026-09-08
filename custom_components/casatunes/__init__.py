"""The CasaTunes integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CasaTunesClient
from .const import DOMAIN
from .coordinator import CasaTunesDataUpdateCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.MEDIA_PLAYER]
CasaTunesConfigEntry = ConfigEntry[CasaTunesDataUpdateCoordinator]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register actions even when the server is unavailable."""
    from .media_player import DOORBELL_SCHEMA, SEARCH_SCHEMA, TTS_SCHEMA

    for name, schema, method in (
        ("search", SEARCH_SCHEMA, "search"),
        ("tts", TTS_SCHEMA, "async_tts"),
        ("doorbell", DOORBELL_SCHEMA, "async_doorbell"),
    ):
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=Platform.MEDIA_PLAYER,
            schema=schema,
            func=method,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CasaTunesConfigEntry) -> bool:
    """Connect before creating entities."""
    coordinator = CasaTunesDataUpdateCoordinator(
        hass,
        entry,
        CasaTunesClient(async_get_clientsession(hass), entry.data[CONF_HOST]),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CasaTunesConfigEntry) -> bool:
    """Unload through the config-entry lifecycle."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: CasaTunesConfigEntry) -> None:
    """Let Home Assistant manage unload failures and retries."""
    await hass.config_entries.async_reload(entry.entry_id)
