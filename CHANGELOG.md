# Changelog

## 0.2.0

- Replace inherited network methods with one validated, bounded HTTP transport.
- Remove the legacy pycasatunes dependency; use local REST data models and HA's shared aiohttp session.
- Preserve zone unique IDs and native search, TTS and doorbell services.
- Use typed runtime data and current Home Assistant service/discovery interfaces.
- Publish complete poll snapshots and cache system/source metadata.
- Correct shuffle routes, buffering states and playback position timestamps.
- Add repeat, relative volume and standard queue mappings.
- Respect enabled sources and source/zone capabilities.
- Isolate groups to one server and report members from every grouped entity.
- Handle removed zones and discover new zones during polling.
- Add address reconfiguration, redacted diagnostics and power-command debug logs.
- Add API and Home Assistant regression tests and CI.

Requires Home Assistant 2026.9+. Restart Home Assistant after installing.
This release does not claim to fix server-originated idle shutdowns.
