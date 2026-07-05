"""Compatibility helpers for the CasaTunes API client."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from urllib.parse import quote, urlencode

from aiohttp import ClientResponse
from pycasatunes import CasaTunes
from pycasatunes.const import API_PORT
from pycasatunes.exceptions import CasaException
from pycasatunes.objects.nowplaying import CasaTunesNowPlaying
from pycasatunes.objects.source import CasaTunesSource
from pycasatunes.objects.zone import CasaTunesZone

_CasaTunesObjectT = TypeVar("_CasaTunesObjectT")


class CasaTunesClient(CasaTunes):
    """CasaTunes client with defensive response parsing."""

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

        response: ClientResponse = await self._client.get(
            f"http://{self._host}:{API_PORT}{path}"
        )
        response.raise_for_status()
        try:
            payload = await response.json()
        except Exception as exception:
            raise CasaException(
                "CasaTunes returned an invalid JSON response"
            ) from exception
        self.logger.debug(payload)
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

        return [dict(item) for item in items]

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

    async def get_zones(self) -> None:
        """Get zones."""
        payload = await self._get_json("/api/v1/zones")
        self._zones = [
            CasaTunesZone(self._client, zone)
            for zone in self._normalize_collection(payload, "zones", "ZoneID")
        ]
        self._zones_dict = self._index_by(self._zones, "ZoneID")

    async def get_sources(self) -> None:
        """Get sources."""
        payload = await self._get_json("/api/v1/sources")
        self._sources = [
            CasaTunesSource(self._client, source)
            for source in self._normalize_collection(payload, "sources", "SourceID")
        ]
        self._sources_dict = self._index_by(self._sources, "SourceID")

    async def get_nowplaying(self) -> None:
        """Get now playing information."""
        payload = await self._get_json("/api/v1/sources/nowplaying")
        self._nowplaying = [
            CasaTunesNowPlaying(self._client, item)
            for item in self._normalize_collection(payload, "nowplaying", "SourceID")
        ]
        self._nowplaying_dict = self._index_by(self._nowplaying, "SourceID")

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
