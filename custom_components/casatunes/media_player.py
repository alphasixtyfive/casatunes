"""Support for the CasaTunes media player."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.util.dt import utcnow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    MediaPlayerDeviceClass,
)
from homeassistant.helpers import entity_platform

from pycasatunes.objects.zone import CasaTunesZone

from .const import ATTR_KEYWORD, DOMAIN, SERVICE_SEARCH
from .browse_media import build_item_response
from . import CasaTunesDataUpdateCoordinator, CasaTunesDeviceEntity

_LOGGER = logging.getLogger(__name__)

SEARCH_SCHEMA = {vol.Required(ATTR_KEYWORD): str}

# map CasaTunes status codes to MediaPlayerState enums
STATUS_TO_STATE = {
    0: MediaPlayerState.IDLE,
    1: MediaPlayerState.PAUSED,
    2: MediaPlayerState.PLAYING,
    3: MediaPlayerState.ON,
}

SUPPORT_CASATUNES = (
    MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.CLEAR_PLAYLIST
    | MediaPlayerEntityFeature.GROUPING
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_SET
)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the CasaTunes config entry."""
    coordinator: CasaTunesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    unique_id = coordinator.data.system.attributes["MACAddress"]

    players = [
        CasaTunesMediaPlayer(coordinator, zone, unique_id)
        for zone in coordinator.data.zones
    ]
    async_add_entities(players)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEARCH,
        SEARCH_SCHEMA,
        "search",
    )


class CasaTunesMediaPlayer(CasaTunesDeviceEntity, MediaPlayerEntity):
    """Representation of a CasaTunes media player on the network."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        zone: CasaTunesZone,
        unique_id: str,
    ) -> None:
        """Initialize the media player."""
        super().__init__(
            coordinator,
            zone,
            device_id=f"{unique_id}_{zone.ZoneID}",
            zone_id=zone.ZoneID,
        )
        self._attr_unique_id = f"{unique_id}_{zone.ZoneID}"
        self._attr_supported_features = SUPPORT_CASATUNES
        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        self._server = coordinator
        self._zone_id = zone.ZoneID
        self._media_position_updated_at = None

    async def async_added_to_hass(self):
        """Entity added to hass."""
        await super().async_added_to_hass()
        self.coordinator.entities.append(self)

    async def async_will_remove_from_hass(self):
        """Entity removed from hass."""
        await super().async_will_remove_from_hass()
        self.coordinator.entities.remove(self)

    def _media_playback_trackable(self) -> bool:
        """Detect if we have enough media data to track playback."""
        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            duration = nowplaying[idx].CurrSong.Duration
            return duration is not None and duration > 0
        return False

    def _casatunes_entities(self) -> list[CasaTunesMediaPlayer]:
        """Return all media player entities of the system."""
        entities: list[CasaTunesMediaPlayer] = []
        for coord in self.hass.data[DOMAIN].values():
            entities += [
                ent for ent in coord.entities
                if isinstance(ent, CasaTunesMediaPlayer)
            ]
        return entities

    @property
    def is_master(self) -> bool:
        """Return True if this zone is master."""
        return bool(self.zone.SharedRoomID and self.zone.MasterMode)

    @property
    def is_client(self) -> bool:
        """Return True if this zone is a client."""
        return bool(self.zone.SharedRoomID and not self.zone.MasterMode)

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self.zone.GroupName or self.zone.Name

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        if not self.zone.Power:
            return MediaPlayerState.OFF

        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            status = nowplaying[idx].Status
            return STATUS_TO_STATE.get(status, MediaPlayerState.ON)
        return MediaPlayerState.ON

    @property
    def shuffle(self) -> bool | None:
        """Boolean if shuffle is enabled."""
        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            return nowplaying[idx].ShuffleMode
        return None

    @property
    def volume_level(self) -> float | None:
        """Return volume level (0..1)."""
        return self.zone.Volume / 100.0

    @property
    def is_volume_muted(self) -> bool | None:
        """Return True if volume is muted."""
        return self.zone.Mute

    @property
    def source(self) -> str | None:
        """Name of the current input source."""
        for src in self.coordinator.data.sources:
            if src.SourceID == self.zone.SourceID:
                return src.Name
        return None

    @property
    def source_list(self) -> list[str]:
        """List of available input sources."""
        return [
            src.Name for src in self.coordinator.data.sources
            if not src.Hidden
        ]

    @property
    def media_track(self) -> int | None:
        """Return the track number of current media."""
        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            return nowplaying[idx].QueueSongIndex
        return None

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            return nowplaying[idx].CurrSong.Title
        return None

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            return nowplaying[idx].CurrSong.Artists
        return None

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media."""
        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            return nowplaying[idx].CurrSong.Album
        return None

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        if self._media_playback_trackable():
            idx = self.zone.SourceID
            return self.coordinator.data.nowplaying[idx].CurrSong.Duration
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        if self._media_playback_trackable():
            idx = self.zone.SourceID
            self._media_position_updated_at = utcnow()
            return self.coordinator.data.nowplaying[idx].CurrProgress
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the position was last updated."""
        if self._media_playback_trackable():
            return self._media_position_updated_at
        return None

    @property
    def media_content_type(self) -> MediaType:
        """Content type of current playing media."""
        return MediaType.MUSIC

    @property
    def media_image_url(self) -> str | None:
        """Image URL of current playing media."""
        idx = self.zone.SourceID
        nowplaying = self.coordinator.data.nowplaying
        if 0 <= idx < len(nowplaying):
            return nowplaying[idx].CurrSong.ArtworkURI
        return None

    @property
    def media_image_remotely_accessible(self) -> bool:
        return True

    @property
    def group_members(self) -> list[str] | None:
        """Return a list of entity_ids in this zone's group."""
        if not self.is_master:
            return None
        clients = [
            ent.entity_id
            for ent in self._casatunes_entities()
            if ent.is_client and ent.zone_id in {
                z.ZoneID for z in self.coordinator.data.zones if z.SharedRoomID
            }
        ]
        return [self.entity_id] + clients

    @property
    def zone_master(self) -> int | None:
        """Return the master zone ID for this zone."""
        for z in self.coordinator.data.zones:
            if z.MasterMode and z.SharedRoomID == self.zone.SharedRoomID:
                return z.ZoneID
        return None

    async def sync_master(self):
        """Ensure master status is correct after unjoin/join."""
        if not any(ent.is_client for ent in self._casatunes_entities()):
            master = self.zone_master
            if master is not None:
                await self.coordinator.data.zone_master(master, False)
                await self.coordinator.async_refresh()
                _LOGGER.debug("Zone %s is no longer master.", master)

    async def async_turn_on(self):
        await self.coordinator.data.turn_on(self.zone_id)
        await self.coordinator.async_refresh()

    async def async_turn_off(self):
        await self.coordinator.data.turn_off(self.zone_id)
        await self.coordinator.async_refresh()

    async def async_set_volume_level(self, volume: float):
        await self.coordinator.data.set_volume_level(self.zone_id, int(volume * 100))
        await self.coordinator.async_refresh()

    async def async_mute_volume(self, mute: bool):
        await self.coordinator.data.mute_volume(self.zone_id, mute)
        await self.coordinator.async_refresh()

    async def async_media_seek(self, position: int):
        await self.coordinator.data.player_action(self.zone_id, "Position", position)
        self._media_position_updated_at = utcnow()
        await self.coordinator.async_refresh()

    async def async_media_previous_track(self):
        await self.coordinator.data.player_action(self.zone_id, "previous")
        await self.coordinator.async_refresh()

    async def async_media_next_track(self):
        await self.coordinator.data.player_action(self.zone_id, "next")
        await self.coordinator.async_refresh()

    async def async_media_play(self):
        await self.coordinator.data.player_action(self.zone_id, "play")
        await self.coordinator.async_refresh()

    async def async_media_pause(self):
        await self.coordinator.data.player_action(self.zone_id, "pause")
        await self.coordinator.async_refresh()

    async def async_media_stop(self):
        await self.coordinator.data.player_action(self.zone_id, "stop")
        await self.coordinator.async_refresh()

    async def async_set_shuffle(self, shuffle: bool):
        flag = f"ShuffleMode={'true' if shuffle else 'false'}"
        await self.coordinator.data.player_action(self.zone_id, "shuffle", flag)
        await self.coordinator.async_refresh()

    async def async_select_source(self, source: str):
        for src in self.coordinator.data.sources:
            if src.Name == source:
                await self.coordinator.data.change_source(self.zone_id, src.SourceID)
                await self.coordinator.async_refresh()
                await self.sync_master()

    async def async_join_players(self, group_members: list[str]):
        """Join this player with others."""
        await self.coordinator.data.zone_master(self.zone_id, True)
        for ent in self._casatunes_entities():
            if ent.entity_id in group_members and ent != self:
                await self.coordinator.data.zone_join(self.zone_id, ent.zone_id)
        await self.coordinator.async_refresh()
        await self.sync_master()

    async def async_unjoin_player(self):
        """Remove this player from its group."""
        master = self.zone_master
        if master is not None:
            await self.coordinator.data.zone_unjoin(master, self.zone_id)
            await self.coordinator.async_refresh()
            await self.sync_master()

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        """Implement the websocket media browsing helper."""
        return await build_item_response(
            self._zone_id,
            self.coordinator,
            media_content_type,
            media_content_id,
        )

    async def async_play_media(self, media_type, media_id, **kwargs):
        """Play the given media."""
        _LOGGER.debug("Playback request for %s / %s", media_type, media_id)
        await self.coordinator.data.play_media(self.zone_id, media_id)
        await self.coordinator.async_refresh()

    async def async_clear_playlist(self):
        """Clear the current playlist."""
        await self.coordinator.data.clear_playlist(self.zone.SourceID)
        await self.coordinator.async_refresh()

    async def search(self, keyword: str):
        """Search for media by keyword."""
        await self.coordinator.data.search_media(self.zone_id, keyword)
