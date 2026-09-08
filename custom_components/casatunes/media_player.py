"""Support for the CasaTunes media player."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pycasatunes.objects.zone import CasaTunesZone

from .browse_media import CT_ALLOWSELECT, CT_COLLECTION, build_item_response
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
    ATTR_SSML,
    ATTR_VOICE,
    ATTR_VOLUME,
)
from .coordinator import CasaTunesDataUpdateCoordinator
from .entity import CasaTunesDeviceEntity

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
    cv.make_entity_service_schema(
        {
            vol.Optional(ATTR_KEYWORD): cv.string,
            vol.Optional(ATTR_KEYWORD_ARTIST): cv.string,
            vol.Optional(ATTR_KEYWORD_ALBUM): cv.string,
            vol.Optional(ATTR_KEYWORD_TRACK_NAME): cv.string,
            vol.Optional(ATTR_MODE, default=DEFAULT_QUEUE_MODE): vol.In(QUEUE_MODES),
        }
    ),
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
    3: MediaPlayerState.BUFFERING,
    4: MediaPlayerState.BUFFERING,
    5: MediaPlayerState.BUFFERING,
}


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the CasaTunes config entry."""
    coordinator: CasaTunesDataUpdateCoordinator = entry.runtime_data
    unique_id = coordinator.data.system.attributes["MACAddress"]

    known_zones = set()

    @callback
    def add_new_zones():
        players = []
        for zone in coordinator.data.zones:
            if zone.ZoneID not in known_zones:
                known_zones.add(zone.ZoneID)
                players.append(CasaTunesMediaPlayer(coordinator, zone, unique_id))
        if players:
            async_add_entities(players)

    add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(add_new_zones))


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
        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        self._zone_id = zone.ZoneID
        self._attr_entity_registry_enabled_default = not zone.Hidden

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
        return [
            ent
            for ent in self.coordinator.entities
            if isinstance(ent, CasaTunesMediaPlayer)
        ]

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
    def state(self) -> MediaPlayerState | None:
        """Return the state of the device."""
        if not self.zone.Power:
            return MediaPlayerState.OFF

        nowplaying = self._nowplaying
        if nowplaying is not None:
            status = nowplaying.Status
            return STATUS_TO_STATE.get(status, MediaPlayerState.ON)
        return MediaPlayerState.ON

    def _source_enabled(self, source_id: int) -> bool:
        mask = self.zone.EnabledSources
        return mask is None or bool(int(mask) & (1 << int(source_id)))

    @property
    def supported_features(self):
        features = MediaPlayerEntityFeature.GROUPING
        if not self.zone.HidePowerControl:
            features |= (
                MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
            )
        if not self.zone.HideSourceControl:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        if not self.zone.FixedVolumeEnabled:
            features |= (
                MediaPlayerEntityFeature.VOLUME_MUTE
                | MediaPlayerEntityFeature.VOLUME_STEP
            )
            if self.zone.VolumeControlType != 2:
                features |= MediaPlayerEntityFeature.VOLUME_SET
        source = self.coordinator.data.sources_dict.get(self.zone.SourceID)
        if source is None or not ((source.MediaTypesSupported or 0) & 1):
            return features
        features |= (
            MediaPlayerEntityFeature.BROWSE_MEDIA
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.MEDIA_ENQUEUE
        )
        controls = (
            (self._nowplaying.attributes.get("Controls") or 0)
            if self._nowplaying
            else 0
        )
        for mask, feature in (
            (1, MediaPlayerEntityFeature.PLAY),
            (2, MediaPlayerEntityFeature.STOP),
            (4, MediaPlayerEntityFeature.PAUSE),
            (8, MediaPlayerEntityFeature.SHUFFLE_SET),
            (16, MediaPlayerEntityFeature.REPEAT_SET),
            (32, MediaPlayerEntityFeature.NEXT_TRACK),
            (64, MediaPlayerEntityFeature.PREVIOUS_TRACK),
            (256, MediaPlayerEntityFeature.SEEK),
            (0x40000, MediaPlayerEntityFeature.CLEAR_PLAYLIST),
        ):
            if controls & mask:
                features |= feature
        return features

    @property
    def repeat(self):
        if self._nowplaying:
            return {0: RepeatMode.OFF, 1: RepeatMode.ALL, 2: RepeatMode.ONE}.get(
                self._nowplaying.RepeatMode
            )
        return None

    async def async_set_repeat(self, repeat):
        modes = {RepeatMode.OFF: "off", RepeatMode.ALL: "on", RepeatMode.ONE: "once"}
        if repeat not in modes:
            raise ServiceValidationError("Invalid repeat mode")
        await self.coordinator.command(
            "player_action", self.zone_id, "repeat", modes[repeat]
        )

    async def async_volume_up(self):
        await self.coordinator.command("set_zone", self.zone_id, AdjustVolume=1)

    async def async_volume_down(self):
        await self.coordinator.command("set_zone", self.zone_id, AdjustVolume=-1)

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
            src.Name
            for src in self.coordinator.data.sources
            if not src.Hidden and self._source_enabled(src.SourceID)
        ]

    @property
    def media_track(self) -> int | None:
        """Return the track number of current media."""
        nowplaying = self._nowplaying
        if nowplaying is not None:
            return None  # Queue index is not an album track number.
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
            return self._nowplaying.CurrProgress
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the position was last updated."""
        if self._media_playback_trackable():
            return self.coordinator.updated_at
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
                return self.coordinator.client.image_url(image)
        return None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Return whether clients can fetch the image URL directly."""
        return False

    @property
    def group_members(self) -> list[str] | None:
        """Return a list of entity_ids in this zone's group."""
        group = self._group_entities()
        if not group:
            return [self.entity_id]
        return [
            ent.entity_id for ent in sorted(group, key=lambda ent: not ent.is_master)
        ]

    @property
    def zone_master(self) -> int | None:
        """Return the master zone ID for this zone."""
        if not self.zone.SharedRoomID:
            return None

        for z in self.coordinator.data.zones:
            if z.MasterMode and z.SharedRoomID == self.zone.SharedRoomID:
                return z.ZoneID
        return None

    async def async_turn_on(self):
        await self.coordinator.command("turn_on", self.zone_id)

    async def async_turn_off(self):
        await self.coordinator.command("turn_off", self.zone_id)

    async def async_set_volume_level(self, volume: float):
        await self.coordinator.command(
            "set_volume_level", self.zone_id, int(volume * 100)
        )

    async def async_mute_volume(self, mute: bool):
        await self.coordinator.command("mute_volume", self.zone_id, mute)

    async def async_media_seek(self, position: int):
        await self.coordinator.command(
            "player_action", self.zone_id, "Position", position
        )

    async def async_media_previous_track(self):
        await self.coordinator.command("player_action", self.zone_id, "previous")

    async def async_media_next_track(self):
        await self.coordinator.command("player_action", self.zone_id, "next")

    async def async_media_play(self):
        await self.coordinator.command("player_action", self.zone_id, "play")

    async def async_media_pause(self):
        await self.coordinator.command("player_action", self.zone_id, "pause")

    async def async_media_stop(self):
        await self.coordinator.command("player_action", self.zone_id, "stop")

    async def async_set_shuffle(self, shuffle: bool):
        flag = shuffle
        await self.coordinator.command("player_action", self.zone_id, "shuffle", flag)

    async def async_select_source(self, source: str):
        for src in self.coordinator.data.sources:
            if (
                src.Name == source
                and not src.Hidden
                and self._source_enabled(src.SourceID)
            ):
                await self.coordinator.command(
                    "change_source", self.zone_id, src.SourceID
                )
                return
        raise ServiceValidationError(f"Source is not available in this zone: {source}")

    async def async_join_players(self, group_members: list[str]):
        """Join this player with others."""
        entities = {
            ent.entity_id: ent for ent in self._casatunes_entities() if ent.available
        }
        if any(member not in entities for member in group_members):
            raise ServiceValidationError(
                "All grouped players must belong to this CasaTunes server"
            )
        members = [
            entities[member] for member in group_members if member != self.entity_id
        ]
        if not members:
            return
        await self.coordinator.command("zone_master", self.zone_id, True)
        for ent in members:
            await self.coordinator.command("zone_join", self.zone_id, ent.zone_id)

    async def async_unjoin_player(self):
        """Detach clients, or dissolve a group when its leader leaves."""
        master = self.zone_master
        if master is None:
            return
        if self.is_master:
            for ent in self._group_entities():
                if ent is not self:
                    await self.coordinator.command("zone_unjoin", master, ent.zone_id)
        else:
            await self.coordinator.command("zone_unjoin", master, self.zone_id)
        # Group cleanup depends on the completed mutation, so bypass debounce here.
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            return
        leader = next(
            (ent for ent in self._casatunes_entities() if ent.zone_id == master), None
        )
        if leader is not None and not any(
            ent.is_client for ent in leader._group_entities()
        ):
            await self.coordinator.command("zone_master", master, False)

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
        if kwargs.get("announce"):
            raise ServiceValidationError(
                "URL announcements are not supported; use casatunes.tts"
            )
        enqueue = kwargs.get("enqueue")
        modes = {
            None: None,
            MediaPlayerEnqueue.REPLACE: "playNow",
            MediaPlayerEnqueue.ADD: "add",
            MediaPlayerEnqueue.PLAY: "addplay",
        }
        if enqueue not in modes:
            raise ServiceValidationError(
                "CasaTunes does not support inserting media next"
            )
        if media_type not in (
            "library",
            MediaType.TRACK,
            MediaType.MUSIC,
            MediaType.PLAYLIST,
        ):
            raise ServiceValidationError("Use a CasaTunes media ID from Browse Media")
        await self.coordinator.command(
            "play_media", self.zone_id, media_id, add_to_queue=modes[enqueue]
        )

    async def async_clear_playlist(self):
        """Clear the current playlist."""
        await self.coordinator.command("clear_zone_queue", self.zone_id)

    async def search(self, **service_data):
        """Search for media and play or queue the best match."""
        search_text = _build_search_text(service_data)
        result = await self.coordinator.command(
            "search_media", self.zone_id, search_text
        )
        if not isinstance(result, dict):
            raise ServiceValidationError("Invalid CasaTunes search response")
        item = _best_search_item(result, service_data)
        if item is None:
            raise ServiceValidationError(f"No CasaTunes media found for {search_text}")

        mode = service_data.get(ATTR_MODE, DEFAULT_QUEUE_MODE)
        await self.coordinator.command("queue_media", self.zone_id, item["ID"], mode)

    async def async_tts(self, **service_data):
        """Play text-to-speech in this zone."""
        await self.coordinator.command("tts", self.zone_id, service_data)

    async def async_doorbell(self, **service_data):
        """Play a doorbell chime in this zone."""
        await self.coordinator.command("doorbell", self.zone_id, service_data)
