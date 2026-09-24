# OctoPrint-KlipperVirtualSD

Use OctoPrint's normal **Print** workflow while executing the G-code through
Klipper's `virtual_sdcard`.

The goal is simple: keep OctoPrint as the UI, job tracker and plugin host, but
remove live G-code streaming from the timing-critical path.

## Why?

Klipper can execute a file directly through `virtual_sdcard`, which avoids
host-side G-code starvation and streaming stalls. OctoPrint, however, normally
treats firmware-SD jobs differently from local jobs, so useful metadata and
plugin integrations may disappear.

This plugin bridges the two worlds:

- click **Print** on a normal OctoPrint local file;
- OctoPrint starts it as a firmware-SD job;
- Klipper executes the same file through `virtual_sdcard`;
- OctoPrint still tracks progress and job state;
- local metadata is restored for plugins that expect it.

## Features

- Normal Cura → OctoPrint → **Print** workflow.
- Klipper `virtual_sdcard` execution.
- Native OctoPrint firmware-SD progress tracking.
- Clean cancel handling.
- Filters Marlin-specific commands that are problematic with Klipper.
- Suppresses unnecessary idle SD polling.
- Restores local file metadata for virtual-SD jobs:
  - filament length and volume;
  - estimated print time;
  - file date;
  - file size.
- Tested with SpoolManager, PrintJobHistory and Dashboard.
- Optional automatic MCU recovery after OctoPrint reconnects.

## Requirements

- Klipper with `[virtual_sdcard]`.
- OctoPrint.
- The Klipper virtual-SD path must point to the same directory where
  OctoPrint stores uploaded G-code files.
- If automatic MCU recovery is enabled, the OctoPrint service user must have
  read/write access to the Klippy API socket (by default
  `/run/klipper/klippy.sock`) and access to its parent directory.

Example Klipper configuration:

```ini
[virtual_sdcard]
path: /home/octoprint/.octoprint/uploads
on_error_gcode:
    CANCEL_PRINT
```

The Klipper process must have permission to read that directory.

For the Klippy API socket, a shared group between the Klipper and OctoPrint
services is a convenient setup. For example, the socket may look like:

```text
srwxrwx--- klipper 3d_print /run/klipper/klippy.sock
```

with the `octoprint` user belonging to the `3d_print` group.

## Automatic MCU recovery

Version 0.9.0 can recover automatically when OctoPrint reconnects while Klipper
is in `shutdown` or `error` because the MCU was powered off or restarted.

The plugin queries Klipper through its official Unix-domain API socket:

- `ready` → do nothing;
- `startup` → wait briefly and query once more;
- `shutdown` or `error` → request `gcode/firmware_restart`;
- active or paused OctoPrint job → never restart automatically.

This feature is optional and can be disabled in the plugin settings.

By default the plugin expects the Klippy API socket at:

```text
/run/klipper/klippy.sock
```

Klipper must be started with the `-a` option pointing to that socket, for
example:

```text
-a /run/klipper/klippy.sock
```

The OctoPrint process also needs permission to connect to the socket. A shared
group between the Klipper and OctoPrint services is a convenient way to grant
that access.

## Installation

Install directly from the repository URL in OctoPrint's Plugin Manager, or
install a packaged release ZIP.

After installation, restart OctoPrint.

Keep **firmware SD support enabled** in OctoPrint.

## Tested environment

Known working setup:

- OctoPrint 1.11.7
- Klipper
- shared OctoPrint uploads / Klipper `virtual_sdcard` directory
- Klippy API socket at `/run/klipper/klippy.sock`

Other versions may work but have not yet been validated.

## How it works

OctoPrint still believes it is tracking a firmware-SD print, while the file
actually remains in its local uploads directory and Klipper reads it directly.

The plugin provides compatibility shims so OctoPrint and its plugins can still
resolve the virtual-SD file against local storage and access the original
analysis metadata.

For automatic MCU recovery, the plugin uses Klipper's JSON API over the Klippy
Unix socket instead of parsing terminal output.

## Caveats

This plugin intentionally relies on some OctoPrint internal interfaces to
bridge local-file and firmware-SD behaviour. Test new OctoPrint versions before
upgrading a production printer.

Automatic MCU recovery requires a working and accessible Klippy API socket.
If the socket is missing or inaccessible, the recovery check is skipped and the
rest of the plugin continues to work normally.

## License

MIT.
