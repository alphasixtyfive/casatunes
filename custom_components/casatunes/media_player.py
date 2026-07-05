"""Support for the CasaTunes media player."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
import voluptuous as vol

from homeassistant.util.dt import utcnow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    MediaPlayerDeviceClass,
)
from homeassistant.helpers import config_validation as cv, entity_platform

from pycasatunes.objects.zone import CasaTunesZone

from .const import (
    ATTR_CHIME,
    ATTR_GENDER,
    ATTR_INPUT,
    ATTR_KEYWORD,
    ATTR_KEYWORD_ALBUM,
    ATTR_KEYWORD_ARTIST,
    ATTR_KEYWORD_TRACK_NAME,
    ATTR_LANGUAGE_CODE,
    ATTR_MODE,
    ATTR_POST_WAIT,
    ATTR_PRE_WAIT,
    ATTR_VOLUME,
    ATTR_SSML,
    ATTR_VOICE,
    DOMAIN,
    SERVICE_DOORBELL,
    SERVICE_SEARCH,
    SERVICE_TTS,
)
from .browse_media import CT_ALLOWSELECT, CT_COLLECTION, build_item_response
from . import CasaTunesDataUpdateCoordinator, CasaTunesDeviceEntity

_LOGGER = logging.getLogger(__name__)

DEFAULT_QUEUE_MODE = "add"
QUEUE_MODES = ["playNow", "playShuffle", "playUnshuffle", "add", "addplay"]
SEARCH_TEXT_FIELDS = [
    ATTR_KEYWORD,
    ATTR_KEYWORD_ARTIST,
    ATTR_KEYWORD_ALBUM,
    ATTR_KEYWORD_TRACK_NAME,
]


def _require_search_text(data: dict) -> dict:
    """Validate that at least one search field is present."""
    if not any(data.get(field) for field in SEARCH_TEXT_FIELDS):
        raise vol.Invalid("At least one search field is required")
    return data


SEARCH_SCHEMA = vol.All(
    {
        vol.Optional(ATTR_KEYWORD): cv.string,
        vol.Optional(ATTR_KEYWORD_ARTIST): cv.string,
        vol.Optional(ATTR_KEYWORD_ALBUM): cv.string,
        vol.Optional(ATTR_KEYWORD_TRACK_NAME): cv.string,
        vol.Optional(ATTR_MODE, default=DEFAULT_QUEUE_MODE): vol.In(QUEUE_MODES),
    },
    _require_search_text,
)

WAIT_SCHEMA = vol.All(vol.Coerce(float), vol.Range(min=0, max=5))
VOLUME_SCHEMA = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))

TTS_SCHEMA = {
    vol.Required(ATTR_INPUT): cv.string,
    vol.Optional(ATTR_SSML): cv.boolean,
    vol.Optional(ATTR_LANGUAGE_CODE): cv.string,
    vol.Optional(ATTR_GENDER): vol.In(
        ["MALE", "FEMALE", "NEUTRAL", "Male", "Female", "Neutral"]
    ),
    vol.Optional(ATTR_VOICE): cv.string,
    vol.Optional(ATTR_PRE_WAIT): WAIT_SCHEMA,
    vol.Optional(ATTR_POST_WAIT): WAIT_SCHEMA,
    vol.Optional(ATTR_VOLUME): VOLUME_SCHEMA,
}

DOORBELL_SCHEMA = {
    vol.Optional(ATTR_CHIME): cv.string,
    vol.Optional(ATTR_PRE_WAIT): WAIT_SCHEMA,
    vol.Optional(ATTR_POST_WAIT): WAIT_SCHEMA,
    vol.Optional(ATTR_VOLUME): VOLUME_SCHEMA,
}


def _normalize_text(value: Any) -> str:
    """Return a normalized string for search matching."""
    return str(value).casefold() if value not in (None, "") else ""


def _build_search_text(service_data: dict[str, Any]) -> str:
    """Build the CasaTunes search text from service fields."""
    if keyword := service_data.get(ATTR_KEYWORD):
        return str(keyword)

    return " ".join(
        str(service_data[field])
        for field in (ATTR_KEYWORD_ARTIST, ATTR_KEYWORD_ALBUM, ATTR_KEYWORD_TRACK_NAME)
        if service_data.get(field)
    )


def _search_score(item: dict[str, Any], service_data: dict[str, Any]) -> int:
    """Score a CasaTunes search result for structured service input."""
    title = _normalize_text(item.get("Title"))
    artists = _normalize_text(item.get("Artists"))
    album = _normalize_text(item.get("Album"))
    value = _normalize_text(item.get("Value"))
    group_name = _normalize_text(item.get("GroupName"))
    haystack = " ".join([title, artists, album, value, group_name])

    score = 0
    if artist := _normalize_text(service_data.get(ATTR_KEYWORD_ARTIST)):
        if artist in artists or artist in title or artist in value:
            score += 30
        if "artist" in group_name:
            score += 10

    if album_query := _normalize_text(service_data.get(ATTR_KEYWORD_ALBUM)):
        if album_query in album or album_query in title or album_query in value:
            score += 20
        if "album" in group_name:
            score += 10

    if track := _normalize_text(service_data.get(ATTR_KEYWORD_TRACK_NAME)):
        if track in title or track in value:
            score += 40
        if "track" in group_name or "song" in group_name:
            score += 10

    if keyword := _normalize_text(service_data.get(ATTR_KEYWORD)):
        if keyword in haystack:
            score += 10

    return score


def _is_playable_item(item: dict[str, Any]) -> bool:
    """Return whether CasaTunes can play/select a media item directly."""
    flags = item.get("Flags")
    if not isinstance(flags, int):
        return True

    return not flags & CT_COLLECTION or bool(flags & CT_ALLOWSELECT)


def _best_search_item(
    result_detail: dict[str, Any], service_data: dict[str, Any]
) -> dict[str, Any] | None:
    """Choose the best playable CasaTunes search result."""
    items = [
        item
        for item in result_detail.get("MediaItems", [])
        if isinstance(item, dict) and item.get("ID") and _is_playable_item(item)
    ]
    if not items:
        return None

    if not any(
        service_data.get(field)
        for field in (ATTR_KEYWORD_ARTIST, ATTR_KEYWORD_ALBUM, ATTR_KEYWORD_TRACK_NAME)
    ):
        return items[0]

    return max(items, key=lambda item: _search_score(item, service_data))

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
    platform.async_register_entity_service(
        SERVICE_TTS,
        TTS_SCHEMA,
        "async_tts",
    )
    platform.async_register_entity_service(
        SERVICE_DOORBELL,
        DOORBELL_SCHEMA,
        "async_doorbell",
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
        if self in self.coordinator.entities:
            self.coordinator.entities.remove(self)

    @property
    def _nowplaying(self):
        """Return now playing data for this zone's source."""
        return self.coordinator.data.nowplaying_dict.get(self.zone.SourceID)

    def _media_playback_trackable(self) -> bool:
        """Detect if we have enough media data to track playback."""
        nowplaying = self._nowplaying
        if nowplaying is not None:
            duration = nowplaying.CurrSong.Duration
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

    def _group_entities(self) -> list[CasaTunesMediaPlayer]:
        """Return entities in this zone's CasaTunes group."""
        if not self.zone.SharedRoomID:
            return []

        return [
            ent
            for ent in self._casatunes_entities()
            if ent.zone.SharedRoomID == self.zone.SharedRoomID
        ]

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

        nowplaying = self._nowplaying
        if nowplaying is not None:
            status = nowplaying.Status
            return STATUS_TO_STATE.get(status, MediaPlayerState.ON)
        return MediaPlayerState.ON

    @property
    def shuffle(self) -> bool | None:
        """Boolean if shuffle is enabled."""
        nowplaying = self._nowplaying
        if nowplaying is not None:
            return nowplaying.ShuffleMode
        return None

    @property
    def volume_level(self) -> float | None:
        """Return volume level (0..1)."""
        if self.zone.Volume is None:
            return None
        return self.zone.Volume / 100.0

    @property
    def is_volume_muted(self) -> bool | None:
        """Return True if volume is muted."""
        return self.zone.Mute

    @property
    def source(self) -> str | None:
        """Name of the current input source."""
        if source := self.coordinator.data.sources_dict.get(self.zone.SourceID):
            return source.Name

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
        nowplaying = self._nowplaying
        if nowplaying is not None:
            return nowplaying.QueueSongIndex
        return None

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        nowplaying = self._nowplaying
        if nowplaying is not None:
            return nowplaying.CurrSong.Title
        return None

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        nowplaying = self._nowplaying
        if nowplaying is not None:
            return nowplaying.CurrSong.Artists
        return None

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media."""
        nowplaying = self._nowplaying
        if nowplaying is not None:
            return nowplaying.CurrSong.Album
        return None

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        if self._media_playback_trackable():
            return self._nowplaying.CurrSong.Duration
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        if self._media_playback_trackable():
            self._media_position_updated_at = utcnow()
            return self._nowplaying.CurrProgress
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
        nowplaying = self._nowplaying
        if nowplaying is not None:
            if image := nowplaying.CurrSong.ArtworkURI:
                return self.coordinator.data.image_url(image)
        return None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Return whether clients can fetch the image URL directly."""
        return False

    @property
    def group_members(self) -> list[str] | None:
        """Return a list of entity_ids in this zone's group."""
        if not self.is_master:
            return None
        clients = [ent.entity_id for ent in self._group_entities() if ent.is_client]
        return [self.entity_id] + clients

    @property
    def zone_master(self) -> int | None:
        """Return the master zone ID for this zone."""
        if not self.zone.SharedRoomID:
            return None

        for z in self.coordinator.data.zones:
            if z.MasterMode and z.SharedRoomID == self.zone.SharedRoomID:
                return z.ZoneID
        return None

    async def sync_master(self):
        """Ensure master status is correct after unjoin/join."""
        if not any(ent.is_client for ent in self._group_entities()):
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
                return

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

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
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
        await self.coordinator.data.clear_zone_queue(self.zone_id)
        await self.coordinator.async_refresh()

    async def search(self, **service_data):
        """Search for media and play or queue the best match."""
        search_text = _build_search_text(service_data)
        result = await self.coordinator.data.search_media(self.zone_id, search_text)
        item = _best_search_item(result, service_data)
        if item is None:
            raise HomeAssistantError(f"No CasaTunes media found for {search_text}")

        mode = service_data.get(ATTR_MODE, DEFAULT_QUEUE_MODE)
        await self.coordinator.data.queue_media(self.zone_id, item["ID"], mode)
        await self.coordinator.async_refresh()

    async def async_tts(self, **service_data):
        """Play text-to-speech in this zone."""
        await self.coordinator.data.tts(self.zone_id, service_data)
        await self.coordinator.async_refresh()

    async def async_doorbell(self, **service_data):
        """Play a doorbell chime in this zone."""
        await self.coordinator.data.doorbell(self.zone_id, service_data)
        await self.coordinator.async_refresh()
