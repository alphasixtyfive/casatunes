"""Integration tests against real Home Assistant classes and lifecycle."""

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo
from homeassistant.util.dt import utcnow
from pycasatunes.exceptions import CasaException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.casatunes.api import CasaTunesClient
from custom_components.casatunes.coordinator import CasaTunesDataUpdateCoordinator
from custom_components.casatunes.media_player import CasaTunesMediaPlayer


async def snapshot(power=True, status=0, controls=511, source_type=1):
    client = CasaTunesClient(None, "server")
    client._get_json = AsyncMock(
        side_effect=[
            [
                {
                    "ZoneID": 5,
                    "Name": "Study",
                    "Power": power,
                    "SourceID": 3,
                    "EnabledSources": 8,
                }
            ],
            [
                {
                    "SourceID": 3,
                    "Status": status,
                    "Controls": controls,
                    "CurrProgress": 10,
                    "CurrSong": {"Duration": 200},
                }
            ],
            {"MACAddress": "aa:bb:cc:dd:ee:ff", "AppName": "CasaTunes"},
            [
                {"SourceID": 3, "Name": "PCs", "MediaTypesSupported": source_type},
                {"SourceID": 0, "Name": "Other", "MediaTypesSupported": 1},
            ],
        ]
    )
    return await client.fetch()


async def player(hass, **kwargs):
    entry = MockConfigEntry(domain="casatunes", data={"host": "server"})
    coordinator = CasaTunesDataUpdateCoordinator(hass, entry, AsyncMock())
    coordinator.async_set_updated_data(await snapshot(**kwargs))
    coordinator.updated_at = utcnow()
    ent = CasaTunesMediaPlayer(
        coordinator, coordinator.data.zones[0], "aa:bb:cc:dd:ee:ff"
    )
    ent.entity_id = "media_player.study"
    ent.hass = hass
    coordinator.entities = [ent]
    coordinator.async_request_refresh = AsyncMock()
    return ent


@pytest.mark.parametrize(
    "status,expected",
    [
        (0, "idle"),
        (1, "paused"),
        (2, "playing"),
        (3, "buffering"),
        (4, "buffering"),
        (5, "buffering"),
        (99, "on"),
    ],
)
async def test_states(hass, status, expected):
    ent = await player(hass, status=status)
    assert ent.state == expected


async def test_power_precedes_playback(hass):
    ent = await player(hass, power=False, status=2)
    assert ent.state == "off"


async def test_position_has_no_read_side_effect(hass):
    ent = await player(hass)
    timestamp = ent.media_position_updated_at
    assert ent.media_position == 10
    assert ent.media_position_updated_at == timestamp
    assert ent.media_position == 10
    assert ent.media_position_updated_at == timestamp


async def test_source_and_feature_filtering(hass):
    ent = await player(hass, source_type=4)
    assert ent.source_list == ["PCs"]
    assert not ent.supported_features & F.SEEK
    assert ent.supported_features & F.TURN_ON
    with pytest.raises(ServiceValidationError):
        await ent.async_select_source("Other")
    ent.coordinator.client.change_source.assert_not_called()


async def test_missing_zone_unavailable(hass):
    ent = await player(hass)
    ent.coordinator.data.zones_dict.clear()
    assert not ent.available
    assert ent.state == "idle"


async def test_cross_server_group_rejected_before_commands(hass):
    ent = await player(hass)
    with pytest.raises(ServiceValidationError):
        await ent.async_join_players(["media_player.other_server"])
    ent.coordinator.client.zone_master.assert_not_called()


async def test_shuffle_and_power(hass):
    ent = await player(hass)
    await ent.async_set_shuffle(True)
    ent.coordinator.client.player_action.assert_awaited_once_with(5, "shuffle", True)
    await ent.async_turn_on()
    ent.coordinator.client.turn_on.assert_awaited_once_with(5)


async def test_action_errors(hass):
    ent = await player(hass)
    ent.coordinator.client.turn_on.side_effect = CasaException("failed")
    with pytest.raises(HomeAssistantError):
        await ent.async_turn_on()


async def test_setup_services_and_unload(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain="casatunes", data={"host": "server"}, unique_id="aa:bb:cc:dd:ee:ff"
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.casatunes.api.CasaTunesClient.fetch",
        return_value=await snapshot(),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.services.has_service("casatunes", "search")
    assert hass.services.has_service("casatunes", "tts")
    assert hass.services.has_service("casatunes", "doorbell")
    assert entry.runtime_data.entities
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_ssdp_flow(hass, enable_custom_integrations):
    with patch(
        "custom_components.casatunes.api.CasaTunesClient.fetch",
        return_value=await snapshot(),
    ):
        result = await hass.config_entries.flow.async_init(
            "casatunes",
            context={"source": "ssdp"},
            data=SsdpServiceInfo(
                ssdp_usn="uuid:test",
                ssdp_st="test",
                ssdp_location="http://server/desc.xml",
                upnp={"friendlyName": "CasaTunes"},
            ),
        )
    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"


async def test_user_flow_unreachable(hass, enable_custom_integrations):
    with patch(
        "custom_components.casatunes.api.CasaTunesClient.fetch",
        side_effect=CasaException("offline"),
    ):
        result = await hass.config_entries.flow.async_init(
            "casatunes", context={"source": "user"}, data={"host": "server"}
        )
    assert result["errors"] == {"base": "cannot_connect"}
