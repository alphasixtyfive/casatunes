"""Shared polling and action error handling."""

import asyncio
import logging
from datetime import timedelta

from aiohttp import ClientError
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow
from pycasatunes.exceptions import CasaException

from .api import CasaTunesClient, CasaTunesData
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class CasaTunesDataUpdateCoordinator(DataUpdateCoordinator[CasaTunesData]):
    """Publish complete snapshots and coalesce action refreshes."""

    def __init__(self, hass, entry, client: CasaTunesClient):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=15),
        )
        self.client = client
        self.entities = []
        self.updated_at = None
        self.command_lock = asyncio.Lock()

    async def _async_update_data(self):
        try:
            async with asyncio.timeout(35):
                data = await self.client.fetch()
        except (CasaException, ClientError, TimeoutError) as err:
            raise UpdateFailed("Error communicating with CasaTunes") from err
        self.updated_at = utcnow()
        return data

    async def command(self, method, *args, **kwargs):
        """Serialize commands; surface server errors to action callers."""
        try:
            async with self.command_lock:
                result = await getattr(self.client, method)(*args, **kwargs)
        except (CasaException, ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed"
            ) from err
        await self.async_request_refresh()
        return result
