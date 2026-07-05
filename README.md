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
