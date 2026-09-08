# CasaTunes

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

[CasaTunes](https://www.casatunes.com/) is a Multi-Room audio system. With CasaTunes, you can pick and choose from our flexible line of music servers and matrix amplifiers to create the perfect multiroom audio solution for your customers, whether looking for an entry, value, or high performance solution.

## Maintenance status

This repository is a community-maintained fork of the original CasaTunes custom integration for Home Assistant. The goal is to keep the integration working with current Home Assistant releases and real CasaTunes REST API behavior as long as practical.

Support is best-effort. Issues and pull requests are welcome, especially with Home Assistant logs, CasaTunes API responses, and details about the CasaTunes server version being used.

The original upstream repository is not currently maintained for newer Home Assistant releases. This fork is the maintained version for users who need an actively updated CasaTunes integration.

## Installation

### Installation via Home Assistant Community Store (HACS)
1. Ensure [HACS](http://hacs.xyz/) is installed.
2. Add this repository URL to custom repositories in HACS.
3. Install and restart Home Assistant.
4. If CasaTunes isn't detected after restart you should be able to add it via the integrations screen.

### Manual installation
Download or clone and copy the folder `custom_components/casatunes` into your Home Assistant `custom_components/` directory.

## Discovery
Your CasaTunes unit should be discovered automatically. If this doesn't happen, go to integrations and add it manually with the IP address of your unit.

## Current focus

- Keep the integration compatible with recent Home Assistant versions.
- Work around CasaTunes REST API payload shape differences that can otherwise crash polling.
- Improve media browsing, now-playing data, artwork proxying, grouping, search, TTS, and doorbell behavior.

## Version 0.2.0

Requires Home Assistant 2026.9 or newer. Existing zone unique IDs and the
`casatunes.search`, `casatunes.tts`, and `casatunes.doorbell` actions are preserved.
Restart Home Assistant after updating Python files.

The integration uses local HTTP on port 8735. CasaTunes deliberately supports
control through GET requests. All requests have a ten-second timeout, validate
HTTP and application-level errors, and release their connections. No automatic
retry is made for commands that might already have executed.

Zone and playback data are polled every 15 seconds; system and source metadata
are cached for five minutes. Failed polls do not publish partially updated data.
Entities become unavailable when communication fails or a zone disappears.
New zones are discovered during polling. Hidden zones are disabled by default
when first created.

Supported controls depend on the selected source and zone settings. Shuffle,
repeat, buffering states, relative volume, enabled sources and group membership
follow the server API. Groups must belong to the same CasaTunes server.
Playback position timestamps represent received data, rather than property reads.

Browse Media provides CasaTunes media IDs. Generic URLs, Home Assistant media
source URLs and the standard URL announcement option are not supported.
Queue options `add`, `play`, and `replace` are supported; `next` is rejected
because the documented CasaTunes queue API has no equivalent. Native TTS and
doorbell actions remain available.

To change the server address, use **Settings → Devices & services → CasaTunes →
Reconfigure**. The new address must identify the same server.
To remove the integration, delete its entry in Devices & services; this does
not alter CasaTunes server settings.

## Troubleshooting and diagnostics

Download diagnostics from the integration entry. They include power, sleep,
source IDs and group status, but omit IP/MAC addresses, room names and media titles.
Enable debug logging for `custom_components.casatunes` to record power-command
intent. The integration does not implement a shutdown timer or a keep-on guard.
A keep-on automation is a separate, user-controlled workaround, not a server fix.

If a zone switches off, compare CasaTunes zone status with Home Assistant traces
and command logs. A missing HA logbook context does not establish who sent a
power-off request. Caller attribution may require server logs or network tracing.

## Development

Use Python 3.14 on Linux with Home Assistant 2026.9.1:

```sh
pip install -r requirements_test.txt
ruff check custom_components tests
pytest -q
```

The API contract tests also run without Home Assistant. CI additionally exercises
real Home Assistant setup, unload, discovery, failures, entity state and services.
See the server's `http://SERVER/casadev/` documentation and
`http://SERVER:8735/api/v1/resources` for its installed API definitions.

## Known CasaTunes API issue

Some CasaTunes servers can return duplicate rows for custom Internet Stations and Favorites from the CasaTunes API itself. This integration does not hide those duplicates with a Home Assistant-side filter, so the underlying CasaTunes data/cache issue remains visible and can be fixed at the source.

## Attributions
- [alphasixtyfive] for maintaining this fork.
- [jonkristian] for the earlier CasaTunes integration work this fork is based on.
- This component uses the excellent [integration_blueprint] from [ludeeus].

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

[casatunes]: https://github.com/alphasixtyfive/casatunes
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/alphasixtyfive/casatunes.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintenance-best%20effort-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/v/release/alphasixtyfive/casatunes.svg?style=for-the-badge
[releases]: https://github.com/alphasixtyfive/casatunes/releases
[exampleimg]: example.png
[integration_blueprint]: https://github.com/ludeeus/integration_blueprint
[ludeeus]: https://github.com/ludeeus/
[alphasixtyfive]: https://github.com/alphasixtyfive/
[jonkristian]: https://github.com/jonkristian/
