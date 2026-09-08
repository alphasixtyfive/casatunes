"""Small data models for the documented CasaTunes REST fields."""


class CasaException(Exception):
    """A transport or protocol failure."""


class CasaTunesObject:
    """Retain one validated JSON record without any network behavior."""

    def __init__(self, client, attributes):
        self.attributes = dict(attributes)


class CasaTunesSystem(CasaTunesObject):
    """Read-only accessors for System data."""

    @property
    def MACAddress(self):
        return self.attributes.get("MACAddress", "")

    @property
    def AppName(self):
        return self.attributes.get("AppName", "")

    @property
    def CasaTunesVersion(self):
        return self.attributes.get("CasaTunesVersion", "")

    @property
    def RESTServicesVersion(self):
        return self.attributes.get("RESTServicesVersion", "")


class CasaTunesZone(CasaTunesObject):
    """Read-only accessors for Zone data."""

    @property
    def ZoneID(self):
        return self.attributes.get("ZoneID", None)

    @property
    def Name(self):
        return self.attributes.get("Name", "")

    @property
    def Power(self):
        return self.attributes.get("Power", None)

    @property
    def SourceID(self):
        return self.attributes.get("SourceID", None)

    @property
    def Volume(self):
        return self.attributes.get("Volume", None)

    @property
    def Mute(self):
        return self.attributes.get("Mute", False)

    @property
    def Hidden(self):
        return self.attributes.get("Hidden", False)

    @property
    def EnabledSources(self):
        return self.attributes.get("EnabledSources", None)

    @property
    def FixedVolumeEnabled(self):
        return self.attributes.get("FixedVolumeEnabled", False)

    @property
    def VolumeControlType(self):
        return self.attributes.get("VolumeControlType", 1)

    @property
    def HidePowerControl(self):
        return self.attributes.get("HidePowerControl", False)

    @property
    def HideSourceControl(self):
        return self.attributes.get("HideSourceControl", False)

    @property
    def SharedRoomID(self):
        return self.attributes.get("SharedRoomID", 0)

    @property
    def MasterMode(self):
        return self.attributes.get("MasterMode", False)

    @property
    def SleepEnabled(self):
        return self.attributes.get("SleepEnabled", False)

    @property
    def DND(self):
        return self.attributes.get("DND", False)


class CasaTunesSource(CasaTunesObject):
    """Read-only accessors for Source data."""

    @property
    def SourceID(self):
        return self.attributes.get("SourceID", None)

    @property
    def Name(self):
        return self.attributes.get("Name", "")

    @property
    def Hidden(self):
        return self.attributes.get("Hidden", False)

    @property
    def MediaTypesSupported(self):
        return self.attributes.get("MediaTypesSupported", 0)

    @property
    def Type(self):
        return self.attributes.get("Type", None)

    @property
    def SourceType(self):
        return self.attributes.get("SourceType")


class CasaTunesNowPlaying(CasaTunesObject):
    """Read-only accessors for NowPlaying data."""

    @property
    def SourceID(self):
        return self.attributes.get("SourceID", None)

    @property
    def Status(self):
        return self.attributes.get("Status", 0)

    @property
    def ShuffleMode(self):
        return self.attributes.get("ShuffleMode", False)

    @property
    def RepeatMode(self):
        return self.attributes.get("RepeatMode", 0)

    @property
    def CurrProgress(self):
        return self.attributes.get("CurrProgress", None)

    @property
    def CurrSong(self):
        return CasaTunesSong(None, self.attributes.get("CurrSong") or {})


class CasaTunesSong(CasaTunesObject):
    """Read-only accessors for Song data."""

    @property
    def Title(self):
        return self.attributes.get("Title", "")

    @property
    def Artists(self):
        return self.attributes.get("Artists", "")

    @property
    def Album(self):
        return self.attributes.get("Album", "")

    @property
    def Duration(self):
        return self.attributes.get("Duration", None)

    @property
    def ArtworkURI(self):
        return self.attributes.get("ArtworkURI", "")
