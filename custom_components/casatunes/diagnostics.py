"""Redacted integration diagnostics, excluding host and personal media data."""


async def async_get_config_entry_diagnostics(hass, entry):
    """Return operational status without addresses or media titles."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "last_update_success": coordinator.last_update_success,
        "server_version": data.system.CasaTunesVersion,
        "rest_version": data.system.RESTServicesVersion,
        "zones": [
            {
                "id": z.ZoneID,
                "power": z.Power,
                "source_id": z.SourceID,
                "sleep_enabled": z.SleepEnabled,
                "dnd": z.DND,
                "master": z.MasterMode,
                "shared_room_id": z.SharedRoomID,
            }
            for z in data.zones
        ],
        "sources": [
            {"id": s.SourceID, "type": s.Type, "media_types": s.MediaTypesSupported}
            for s in data.sources
        ],
    }
