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


async def test_reconfigure_wrong_server(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain="casatunes", data={"host": "old"}, unique_id="different"
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.casatunes.api.CasaTunesClient.fetch",
        return_value=await snapshot(),
    ):
        result = await hass.config_entries.flow.async_init(
            "casatunes",
            context={"source": "reconfigure", "entry_id": entry.entry_id},
            data={"host": "new"},
        )
    assert result["type"] == "abort"
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data["host"] == "old"


async def test_duplicate_user_flow(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain="casatunes", data={"host": "server"}, unique_id="aa:bb:cc:dd:ee:ff"
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.casatunes.api.CasaTunesClient.fetch",
        return_value=await snapshot(),
    ):
        result = await hass.config_entries.flow.async_init(
            "casatunes", context={"source": "user"}, data={"host": "server"}
        )
    assert result["reason"] == "already_configured"


async def test_setup_retry(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain="casatunes", data={"host": "server"})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.casatunes.api.CasaTunesClient.fetch",
        side_effect=CasaException("offline"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state.value == "setup_retry"
    assert hass.services.has_service("casatunes", "tts")


async def test_relative_volume_and_fixed_output(hass):
    ent = await player(hass)
    ent.zone.attributes["VolumeControlType"] = 2
    assert ent.supported_features & F.VOLUME_STEP
    assert not ent.supported_features & F.VOLUME_SET
    await ent.async_volume_up()
    ent.coordinator.client.set_zone.assert_awaited_once_with(5, AdjustVolume=1)
    ent.zone.attributes["FixedVolumeEnabled"] = True
    assert not ent.supported_features & F.VOLUME_STEP


@pytest.mark.parametrize(
    "enqueue,expected", [("replace", "playNow"), ("add", "add"), ("play", "addplay")]
)
async def test_queue_modes(hass, enqueue, expected):
    ent = await player(hass)
    await ent.async_play_media("track", "id", enqueue=enqueue)
    ent.coordinator.client.play_media.assert_awaited_once_with(
        5, "id", add_to_queue=expected
    )


async def test_unsupported_queue_mode_no_command(hass):
    ent = await player(hass)
    with pytest.raises(ServiceValidationError):
        await ent.async_play_media("track", "id", enqueue="next")
    ent.coordinator.client.play_media.assert_not_called()


async def test_browse_and_api_error(hass):
    from homeassistant.components.media_player.errors import BrowseError

    from custom_components.casatunes.browse_media import build_item_response

    ent = await player(hass)
    ent.coordinator.client.get_media.return_value = {
        "MediaItems": [
            {"ID": "album", "Title": "Album", "Flags": 8200},
            {"ID": "song", "Title": "Song", "Flags": 8193},
        ]
    }
    result = await build_item_response(5, ent.coordinator)
    assert len(result.children) == 2
    assert result.children[0].can_play and result.children[0].can_expand
    ent.coordinator.client.get_media.side_effect = CasaException("offline")
    with pytest.raises(BrowseError):
        await build_item_response(5, ent.coordinator)


async def test_diagnostics_redacts_identity(hass):
    from custom_components.casatunes.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    ent = await player(hass)
    result = await async_get_config_entry_diagnostics(
        hass, type("Entry", (), {"runtime_data": ent.coordinator})()
    )
    assert "aa:bb" not in str(result)
    assert "Study" not in str(result)
    assert result["zones"][0]["power"] is True


async def test_group_members_and_last_client_cleanup(hass):
    from pycasatunes.objects.zone import CasaTunesZone

    master = await player(hass)
    coordinator = master.coordinator
    master.zone.attributes.update({"MasterMode": True, "SharedRoomID": 42})
    zone = CasaTunesZone(None, {"ZoneID": 2, "Power": True, "SharedRoomID": 42})
    coordinator.data.zones.append(zone)
    coordinator.data.zones_dict[2] = zone
    client = CasaTunesMediaPlayer(coordinator, zone, "aa:bb:cc:dd:ee:ff")
    client.entity_id = "media_player.client"
    client.hass = hass
    coordinator.entities.append(client)
    assert (
        master.group_members
        == client.group_members
        == ["media_player.study", "media_player.client"]
    )

    async def refresh():
        zone.attributes["SharedRoomID"] = 0

    coordinator.async_refresh = AsyncMock(side_effect=refresh)
    await client.async_unjoin_player()
    coordinator.client.zone_unjoin.assert_awaited_once_with(5, 2)
    coordinator.async_refresh.assert_awaited_once()
    coordinator.client.zone_master.assert_awaited_once_with(5, False)
