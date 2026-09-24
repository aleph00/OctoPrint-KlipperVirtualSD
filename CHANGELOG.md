# Changelog

## 0.9.0 — 2026-09-25

- Add optional automatic MCU recovery after an OctoPrint serial connection.
- Query Klipper through its official Unix-domain API socket instead of parsing terminal output.
- If Klipper reports `ready`, do nothing.
- If Klipper reports `startup`, wait briefly and query once more.
- If Klipper reports `shutdown` or `error`, request `gcode/firmware_restart` through the Klipper API.
- Never restart automatically while OctoPrint reports an active or paused job.
- Add settings for enabling/disabling automatic recovery and configuring the Klippy API socket path.
- Default Klippy API socket: `/run/klipper/klippy.sock`.

## 0.8.1 — 2026-09-24

- Keep the v0.8 metadata compatibility fix.
- Remove temporary diagnostic logging.

## 0.8.0 — 2026-09-24

- Restore local G-code analysis metadata for virtual-SD jobs through both
  `get_current_job()` and `get_current_data()`.
- Makes filament length/volume and estimated print time visible again to
  OctoPrint and plugins such as SpoolManager and PrintJobHistory.

## 0.7.0

- First attempt at restoring local metadata for virtual-SD jobs.

## 0.6.0

- Generic FileManager `sdcard -> local` compatibility layer.
- Fixes file path/metadata access for plugins including PrintJobHistory.

## 0.5.0

- Improve plugin compatibility with virtual-SD file metadata.

## 0.4.0

- Suppress idle `M27` polling.
- Redirect browser metadata access from `sdcard` to local files.

## 0.3.0

- Filter `M108` for Klipper compatibility.

## 0.2.0

- Clean cancellation path and avoid recursive `CANCEL_PRINT`.

## 0.1.0

- Initial release: start OctoPrint local files as Klipper virtual-SD jobs.
