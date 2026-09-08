"""Compatibility helpers for the CasaTunes API client."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any, TypeVar
from urllib.parse import quote, urlencode

from aiohttp import ClientError, ClientSession, ClientTimeout

from .models import (
    CasaException,
    CasaTunesNowPlaying,
    CasaTunesSource,
    CasaTunesSystem,
    CasaTunesZone,
)

_CasaTunesObjectT = TypeVar("_CasaTunesObjectT")


_LOGGER = logging.getLogger(__name__)
API_PORT = 8735
REQUEST_TIMEOUT = ClientTimeout(total=10)


@dataclass(frozen=True)
class CasaTunesData:
    """A complete poll; never publish partially updated collections."""

    system: CasaTunesSystem
    zones: list[CasaTunesZone]
    zones_dict: dict
    sources: list[CasaTunesSource]
    sources_dict: dict
    nowplaying_dict: dict


class CasaTunesClient:
    """CasaTunes client with defensive response parsing."""

    def __init__(self, client: ClientSession, host: str) -> None:
        self._client = client
        self._host = host
        self._static_at = 0.0
        self.data: CasaTunesData | None = None

    async def fetch(self) -> CasaTunesData:
        """Refresh live state, caching system/source metadata for five minutes."""
        old = self.data
        refresh_static = old is None or monotonic() - self._static_at >= 300
        try:
            zones_raw = await self._get_json("/api/v1/zones")
            playing_raw = await self._get_json("/api/v1/sources/nowplaying")
            if refresh_static:
                system_raw = await self._get_json("/api/v1/system/info")
                if not isinstance(system_raw, dict) or not system_raw.get("MACAddress"):
                    raise CasaException("System response missing MAC address")
                system = CasaTunesSystem(self._client, system_raw)
                sources_raw = await self._get_json("/api/v1/sources")
                sources = [
                    CasaTunesSource(self._client, x)
                    for x in self._normalize_collection(
                        sources_raw, "sources", "SourceID"
                    )
                ]
            else:
                system, sources = old.system, old.sources
            zones = [
                CasaTunesZone(self._client, x)
                for x in self._normalize_collection(zones_raw, "zones", "ZoneID")
            ]
            playing = [
                CasaTunesNowPlaying(self._client, x)
                for x in self._normalize_collection(
                    playing_raw, "nowplaying", "SourceID"
                )
            ]
            data = CasaTunesData(
                system,
                zones,
                self._index_by(zones, "ZoneID"),
                sources,
                self._index_by(sources, "SourceID"),
                self._index_by(playing, "SourceID"),
            )
        except (CasaException, ClientError, TimeoutError):
            self._static_at = 0
            raise
        self.data = data
        if refresh_static:
            self._static_at = monotonic()
        return data

    async def set_zone(self, zone_id: int | str, **params: Any) -> Any:
        """Set zone properties; log power intent without personal media data."""
        if "Power" in params:
            _LOGGER.debug("Power command: zone=%s power=%s", zone_id, params["Power"])
        return await self._get_json(
            f"/api/v1/zones/{quote(str(zone_id), safe='')}", params
        )

    async def turn_on(self, zone_id):
        return await self.set_zone(zone_id, Power="on")

    async def turn_off(self, zone_id):
        return await self.set_zone(zone_id, Power="off")

    async def set_volume_level(self, zone_id, volume):
        return await self.set_zone(zone_id, Volume=volume)

    async def mute_volume(self, zone_id, mute):
        return await self.set_zone(zone_id, Mute=mute)

    async def change_source(self, zone_id, source):
        return await self.set_zone(zone_id, SourceID=source)

    async def zone_master(self, zone_id, mode):
        return await self.set_zone(zone_id, MasterMode=mode)

    async def zone_join(self, zone_id, client_zone_id):
        return await self._get_json(f"/api/v1/zones/{zone_id}/group/{client_zone_id}")

    async def zone_unjoin(self, zone_id, client_zone_id):
        return await self._get_json(f"/api/v1/zones/{zone_id}/ungroup/{client_zone_id}")

    async def player_action(self, zone_id, action, option=None):
        path = f"/api/v1/zones/{zone_id}/player/{quote(action.lower(), safe='')}"
        if option is not None:
            if isinstance(option, bool):
                option = str(option).lower()
            path += f"/{quote(str(option), safe='')}"
        return await self._get_json(path)

    @staticmethod
    def _clean_params(params: Mapping[str, Any] | None) -> dict[str, str]:
        """Return query params accepted by the CasaTunes API."""
        if not params:
            return {}

        clean: dict[str, str] = {}
        for key, value in params.items():
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                clean[key] = str(value).lower()
            else:
                clean[key] = str(value)
        return clean

    async def _get_json(
        self, path: str, params: Mapping[str, Any] | None = None
    ) -> Any:
        """Fetch and decode a CasaTunes API response."""
        query = urlencode(self._clean_params(params))
        if query:
            path = f"{path}?{query}"

        try:
            async with self._client.get(
                f"http://{self._host}:{API_PORT}{path}", timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except (ValueError, ClientError, TimeoutError) as exception:
            raise CasaException(
                f"CasaTunes request failed ({type(exception).__name__})"
            ) from exception
        if isinstance(payload, dict):
            error = payload.get("Error")
            if error and (
                not isinstance(error, dict)
                or error.get("Message")
                or error.get("Symbol")
                or (error.get("HttpStatus") or 0) >= 400
            ):
                raise CasaException("CasaTunes rejected the requested operation")
            if payload.get("Result") is False:
                raise CasaException("CasaTunes reported an unsuccessful operation")
        return payload

    @staticmethod
    def _collection_payload(payload: Any, collection_name: str) -> Any:
        """Return the collection part from a CasaTunes response."""
        if not isinstance(payload, Mapping):
            return payload

        for key in (collection_name, collection_name.capitalize()):
            value = payload.get(key)
            if value is not None:
                return value

        return payload

    @classmethod
    def _normalize_collection(
        cls, payload: Any, collection_name: str, id_key: str
    ) -> list[dict[str, Any]]:
        """Normalize list-like or keyed CasaTunes collection payloads."""
        collection = cls._collection_payload(payload, collection_name)

        if collection is None:
            return []

        if isinstance(collection, list):
            items = collection
        elif isinstance(collection, Mapping):
            items = [
                {id_key: key, **value} if id_key not in value else dict(value)
                for key, value in collection.items()
                if isinstance(value, Mapping)
            ]
            if len(items) != len(collection):
                raise CasaException(
                    f"Unexpected CasaTunes {collection_name} payload shape"
                )
        else:
            raise CasaException(
                f"Unexpected CasaTunes {collection_name} payload type: "
                f"{type(collection).__name__}"
            )

        if not all(isinstance(item, Mapping) for item in items):
            raise CasaException(f"Unexpected CasaTunes {collection_name} item type")

        result = []
        seen = set()
        for item in items:
            item = dict(item)
            try:
                if isinstance(item.get(id_key), bool):
                    raise ValueError
                item[id_key] = int(item[id_key])
            except (KeyError, TypeError, ValueError) as err:
                raise CasaException(f"Invalid {id_key}") from err
            if item[id_key] in seen:
                raise CasaException(f"Duplicate {id_key}")
            seen.add(item[id_key])
            if collection_name == "zones" and not isinstance(item.get("Power"), bool):
                raise CasaException("Zone response missing valid Power")
            if collection_name == "nowplaying" and not isinstance(
                item.get("CurrSong"), dict
            ):
                item["CurrSong"] = {}
            result.append(item)
        return result

    @staticmethod
    def _index_by(
        items: list[_CasaTunesObjectT], attribute: str
    ) -> dict[Any, _CasaTunesObjectT]:
        """Index CasaTunes objects by raw and stringified IDs."""
        indexed: dict[Any, _CasaTunesObjectT] = {}
        for item in items:
            key = getattr(item, attribute)
            if key is None:
                continue
            indexed[key] = item
            indexed[str(key)] = item
        return indexed

    def image_url(self, image_id_or_url: str) -> str:
        """Return a fetchable URL for a CasaTunes image ID or external URL."""
        image = str(image_id_or_url)
        if image.startswith(("http://", "https://")):
            return image
        if image.startswith("/"):
            return f"http://{self._host}:{API_PORT}{image}"
        return f"http://{self._host}:{API_PORT}/api/v1/images/{quote(image, safe='')}"

    async def get_media(self, opts: Mapping[str, Any]) -> dict[str, Any]:
        """Get media items for a zone or collection."""
        if item_id := opts.get("item_id"):
            params = {"limit": opts.get("limit"), "offset": opts.get("offset")}
            return await self._get_json(
                f"/api/v1/media/{quote(str(item_id), safe='')}", params
            )

        zone_id = quote(str(opts["zone_id"]), safe="")
        params = {
            "includePlaylists": opts.get("include_playlists"),
            "maxPlaylists": opts.get("max_playlists"),
            "includeOtherPlaylists": opts.get("include_other_playlists"),
            "maxBookmarks": opts.get("max_bookmarks"),
            "includeSelectionHistory": opts.get("include_selection_history"),
        }
        return await self._get_json(f"/api/v1/media/zones/{zone_id}", params)

    async def search_media(
        self, zone_id: int | str, search_text: str, limit: int = 1000
    ) -> dict[str, Any]:
        """Search for media available to a zone."""
        zone = quote(str(zone_id), safe="")
        query = quote(search_text, safe="")
        return await self._get_json(
            f"/api/v1/media/zones/{zone}/search/{query}",
            {"limit": limit},
        )

    async def play_media(
        self,
        zone_id: int | str,
        media_id: str,
        add_to_queue: str | None = None,
        auto_start: bool | None = None,
    ) -> Any:
        """Play a media item in a zone."""
        zone = quote(str(zone_id), safe="")
        media = quote(str(media_id), safe="")
        path = f"/api/v1/media/zones/{zone}/play/{media}"
        if add_to_queue:
            path = f"{path}/addtoqueue/{quote(str(add_to_queue), safe='')}"
        return await self._get_json(path, {"autoStart": auto_start})

    async def queue_media(
        self, zone_id: int | str, media_id: str, queue_mode: str
    ) -> Any:
        """Play or queue a media item using a CasaTunes queue mode."""
        return await self.play_media(zone_id, media_id, add_to_queue=queue_mode)

    async def clear_zone_queue(self, zone_id: int | str) -> Any:
        """Clear the queue for a zone."""
        zone = quote(str(zone_id), safe="")
        return await self._get_json(f"/api/v1/zones/{zone}/queue/delete")

    async def tts(self, zone_id: int | str, query: Mapping[str, Any]) -> Any:
        """Play text-to-speech in a zone or zone group."""
        zone = quote(str(zone_id), safe="")
        message = quote(str(query["input"]), safe="")
        gender = query.get("gender")
        params = {
            "ssml": query.get("ssml"),
            "languageCode": query.get("language_code"),
            "gender": gender.upper() if isinstance(gender, str) else gender,
            "voice": query.get("voice"),
            "preWait": query.get("pre_wait"),
            "postWait": query.get("post_wait"),
            "volume": query.get("volume"),
        }
        return await self._get_json(
            f"/api/v1/system/tts/input/{message}/zones/{zone}", params
        )

    async def doorbell(self, zone_id: int | str, query: Mapping[str, Any]) -> Any:
        """Play a doorbell chime in a zone or zone group."""
        zone = quote(str(zone_id), safe="")
        chime = query.get("chime")
        path = f"/api/v1/system/doorbell/zones/{zone}"
        if chime:
            path = f"{path}/chimes/{quote(str(chime), safe='')}"

        return await self._get_json(
            path,
            {
                "preWait": query.get("pre_wait"),
                "postWait": query.get("post_wait"),
                "volume": query.get("volume"),
            },
        )
