"""Transport contract tests; runnable without Home Assistant."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from pycasatunes.exceptions import CasaException

spec = importlib.util.spec_from_file_location(
    "casatunes_api", Path(__file__).parents[1] / "custom_components/casatunes/api.py"
)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)


class Response:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.exited = True

    def raise_for_status(self):
        if self.error:
            raise self.error

    async def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.mark.parametrize(
    "method,args,suffix",
    [
        ("turn_on", (5,), "/zones/5?Power=on"),
        ("turn_off", (5,), "/zones/5?Power=off"),
        ("mute_volume", (5, False), "/zones/5?Mute=false"),
        ("set_volume_level", (5, 30), "/zones/5?Volume=30"),
        ("change_source", (5, 0), "/zones/5?SourceID=0"),
        ("player_action", (5, "shuffle", True), "/zones/5/player/shuffle/true"),
        ("player_action", (5, "Position", 0), "/zones/5/player/position/0"),
        ("player_action", (5, "pause"), "/zones/5/player/pause"),
        ("zone_join", (5, 2), "/zones/5/group/2"),
        ("zone_unjoin", (5, 2), "/zones/5/ungroup/2"),
        ("zone_master", (5, False), "/zones/5?MasterMode=false"),
        ("clear_zone_queue", (5,), "/zones/5/queue/delete"),
        ("queue_media", (5, "a/b", "add"), "/media/zones/5/play/a%2Fb/addtoqueue/add"),
    ],
)
async def test_command_routes(method, args, suffix):
    response = Response({"Result": True})
    session = Session([response])
    await getattr(api.CasaTunesClient(session, "server"), method)(*args)
    assert session.calls[0][0] == "http://server:8735/api/v1" + suffix
    assert session.calls[0][1]["timeout"].total == 10
    assert response.exited


@pytest.mark.parametrize(
    "payload",
    [{"Result": False}, {"Error": {"Message": "bad"}}, {"Error": {"HttpStatus": 500}}],
)
async def test_application_errors(payload):
    with pytest.raises(CasaException):
        await api.CasaTunesClient(Session([Response(payload)]), "server").turn_on(5)


@pytest.mark.parametrize("error", [TimeoutError(), ClientError(), ValueError()])
async def test_transport_errors(error):
    response = Response(error=error)
    with pytest.raises(CasaException):
        await api.CasaTunesClient(Session([response]), "server").turn_on(5)
    assert response.exited


async def test_encoding_and_zero_parameters():
    session = Session([Response({})])
    await api.CasaTunesClient(session, "server").tts(
        5, {"input": "hello / & ?", "ssml": False, "volume": 0}
    )
    assert "hello%20%2F%20%26%20%3F" in session.calls[0][0]
    assert "ssml=false" in session.calls[0][0]
    assert "volume=0" in session.calls[0][0]


def test_collection_shapes_and_ids():
    result = api.CasaTunesClient._normalize_collection(
        {"zones": {"5": {"Power": True}}}, "zones", "ZoneID"
    )
    assert result == [{"ZoneID": 5, "Power": True}]


@pytest.mark.parametrize(
    "payload",
    [
        [{"ZoneID": 5}],
        [{"ZoneID": None, "Power": True}],
        [{"ZoneID": 1, "Power": True}, {"ZoneID": "1", "Power": True}],
        [None],
        "bad",
    ],
)
def test_invalid_zones(payload):
    with pytest.raises(CasaException):
        api.CasaTunesClient._normalize_collection(payload, "zones", "ZoneID")


async def test_atomic_fetch_and_static_cache():
    client = api.CasaTunesClient(None, "server")
    client._get_json = AsyncMock(
        side_effect=[
            [{"ZoneID": 5, "Power": True}],
            [],
            {"MACAddress": "aa:bb"},
            [],
            [{"ZoneID": 5, "Power": False}],
            CasaException("offline"),
        ]
    )
    before = await client.fetch()
    with pytest.raises(CasaException):
        await client.fetch()
    assert client.data is before
    assert client.data.zones_dict[5].Power
    assert client._get_json.call_count == 6


async def test_static_cache_reduces_poll_requests():
    client = api.CasaTunesClient(None, "server")
    client._get_json = AsyncMock(
        side_effect=[
            [],
            [],
            {"MACAddress": "aa:bb"},
            [],
            [],
            [],
        ]
    )
    await client.fetch()
    await client.fetch()
    assert client._get_json.call_count == 6
