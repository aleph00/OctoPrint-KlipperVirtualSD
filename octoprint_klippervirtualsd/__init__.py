import copy
import json
import os
import socket
import threading
import time

import flask
import octoprint.plugin


class KlipperVirtualSDPlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.SimpleApiPlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.TemplatePlugin,
):
    def on_after_startup(self):
        self._recovery_lock = threading.Lock()
        self._recovery_running = False
        self._install_storage_alias()
        self._install_current_job_alias()
        self._install_current_data_alias()
        self._logger.info(
            "KlipperVirtualSD 0.9.0 ready "
            "(automatic MCU recovery=%s, socket=%s)",
            self._settings.get_boolean(["auto_mcu_recovery"]),
            self._settings.get(["klippy_socket"]),
        )

    def on_shutdown(self):
        self._remove_current_data_alias()
        self._remove_current_job_alias()
        self._remove_storage_alias()

    # ----------------------------------------------------------------------
    # Settings
    # ----------------------------------------------------------------------
    def get_settings_defaults(self):
        return dict(
            auto_mcu_recovery=True,
            klippy_socket="/run/klipper/klippy.sock",
        )

    def get_template_configs(self):
        return [
            dict(
                type="settings",
                name="Klipper Virtual SD",
                custom_bindings=False,
            )
        ]

    # ----------------------------------------------------------------------
    # Automatic MCU recovery through Klipper's official API socket
    # ----------------------------------------------------------------------
    def on_event(self, event, payload):
        if event != "Connected":
            return
        if not self._settings.get_boolean(["auto_mcu_recovery"]):
            return

        # Give the OctoPrint/Klipper serial connection a moment to settle.
        timer = threading.Timer(0.75, self._check_klipper_state_after_connect)
        timer.daemon = True
        timer.start()

    def _check_klipper_state_after_connect(self):
        with self._recovery_lock:
            if self._recovery_running:
                return
            self._recovery_running = True

        try:
            socket_path = self._settings.get(["klippy_socket"])
            if not socket_path:
                self._logger.warning(
                    "Automatic MCU recovery enabled but Klippy socket path "
                    "is empty"
                )
                return

            # `info` is a documented Klipper API endpoint and directly
            # returns the host state: ready/startup/shutdown/error.
            response = self._klippy_api_request(
                socket_path,
                "info",
                params={
                    "client_info": {
                        "name": "OctoPrint-KlipperVirtualSD",
                        "version": "0.9.0",
                    }
                },
                timeout=2.0,
            )

            result = response.get("result", {})
            state = result.get("state")
            state_message = result.get("state_message", "")

            self._logger.info(
                "Klippy API state after OctoPrint connection: %s%s",
                state,
                " (%s)" % state_message if state_message else "",
            )

            if state == "ready":
                # This includes an idle printer as well as a printer that is
                # actively printing.  Never disturb a healthy Klipper session.
                return

            if state == "startup":
                # Startup can be transient.  Wait briefly and query once more
                # instead of restarting a Klipper instance that is still
                # legitimately initializing.
                time.sleep(1.5)
                response = self._klippy_api_request(
                    socket_path,
                    "info",
                    params={
                        "client_info": {
                            "name": "OctoPrint-KlipperVirtualSD",
                            "version": "0.9.0",
                        }
                    },
                    timeout=2.0,
                )
                result = response.get("result", {})
                state = result.get("state")
                state_message = result.get("state_message", "")
                self._logger.info(
                    "Klippy API state after startup retry: %s%s",
                    state,
                    " (%s)" % state_message if state_message else "",
                )
                if state == "ready":
                    return

            if state not in ("shutdown", "error"):
                self._logger.warning(
                    "Klippy API returned unexpected state %r; "
                    "automatic recovery skipped",
                    state,
                )
                return

            # Belt-and-suspenders protection.  A healthy active print should
            # have state=ready, but never restart if OctoPrint says a job is
            # active even if the API state looks abnormal.
            if self._printer.is_printing() or self._printer.is_paused():
                self._logger.warning(
                    "Klippy reports %s but OctoPrint has an active job; "
                    "automatic FIRMWARE_RESTART skipped",
                    state,
                )
                return

            self._logger.warning(
                "Klippy state is %s after OctoPrint connection; "
                "requesting FIRMWARE_RESTART via Klipper API",
                state,
            )

            # Use Klipper's dedicated API endpoint rather than parsing terminal
            # output or injecting a G-code command through OctoPrint.
            try:
                self._klippy_api_request(
                    socket_path,
                    "gcode/firmware_restart",
                    params={},
                    timeout=2.0,
                )
            except (ConnectionResetError, BrokenPipeError, EOFError):
                # A firmware restart may tear down the API connection before
                # the reply reaches us.  That is expected.
                self._logger.info(
                    "Klippy API connection closed during FIRMWARE_RESTART "
                    "(expected)"
                )

        except FileNotFoundError:
            self._logger.warning(
                "Klippy API socket not found at %s; automatic MCU recovery "
                "skipped. Ensure Klipper is started with '-a <socket>'.",
                self._settings.get(["klippy_socket"]),
            )
        except PermissionError:
            self._logger.warning(
                "Permission denied opening Klippy API socket %s; automatic "
                "MCU recovery skipped",
                self._settings.get(["klippy_socket"]),
            )
        except (socket.timeout, TimeoutError):
            self._logger.warning(
                "Timed out while querying Klippy API socket %s; automatic "
                "MCU recovery skipped",
                self._settings.get(["klippy_socket"]),
            )
        except Exception:
            self._logger.exception(
                "Automatic Klipper MCU recovery check failed"
            )
        finally:
            with self._recovery_lock:
                self._recovery_running = False

    def _klippy_api_request(
        self, socket_path, method, params=None, timeout=2.0
    ):
        """
        Send one request to Klipper's Unix-domain API socket.

        Klipper frames JSON messages with ASCII ETX (0x03).  Read until the
        response carrying our request id arrives; ignore unrelated async
        messages if any are present on the connection.
        """
        request_id = int(time.time() * 1000000) & 0x7FFFFFFF
        request = {
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        payload = (
            json.dumps(request, separators=(",", ":")).encode("utf-8")
            + b"\x03"
        )

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
            sock.sendall(payload)

            buffer = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    raise EOFError(
                        "Klippy API connection closed before response"
                    )
                buffer += chunk

                while b"\x03" in buffer:
                    raw, buffer = buffer.split(b"\x03", 1)
                    if not raw:
                        continue
                    message = json.loads(raw.decode("utf-8"))
                    if message.get("id") != request_id:
                        continue
                    if "error" in message:
                        raise RuntimeError(
                            "Klippy API error: %s" % message["error"]
                        )
                    return message

    # ----------------------------------------------------------------------
    # FileManager compatibility layer
    # ----------------------------------------------------------------------
    def _install_storage_alias(self):
        fm = self._file_manager
        if hasattr(fm, "_klippervirtualsd_original_storage"):
            return

        original = fm._storage
        fm._klippervirtualsd_original_storage = original

        def aliased_storage(location):
            if location == "sdcard":
                self._logger.debug(
                    "Aliasing FileManager storage sdcard -> local"
                )
                location = "local"
            return original(location)

        fm._storage = aliased_storage
        self._logger.info(
            "Installed generic FileManager storage alias: sdcard -> local"
        )

    def _remove_storage_alias(self):
        fm = getattr(self, "_file_manager", None)
        if not fm:
            return

        original = getattr(
            fm, "_klippervirtualsd_original_storage", None
        )
        if original:
            fm._storage = original
            try:
                delattr(fm, "_klippervirtualsd_original_storage")
            except Exception:
                pass

    # ----------------------------------------------------------------------
    # Current-job metadata compatibility layer
    # ----------------------------------------------------------------------
    def _install_current_job_alias(self):
        printer = self._printer
        if hasattr(printer, "_klippervirtualsd_original_get_current_job"):
            return

        original = printer.get_current_job
        printer._klippervirtualsd_original_get_current_job = original

        def augmented_get_current_job(*args, **kwargs):
            job = original(*args, **kwargs)
            try:
                return self._augment_virtual_sd_job(job)
            except Exception:
                self._logger.exception(
                    "Could not augment virtual-SD current job metadata"
                )
                return job

        printer.get_current_job = augmented_get_current_job
        self._logger.info(
            "Installed current-job metadata augmentation for virtual SD"
        )

    def _remove_current_job_alias(self):
        printer = getattr(self, "_printer", None)
        if not printer:
            return

        original = getattr(
            printer, "_klippervirtualsd_original_get_current_job", None
        )
        if original:
            printer.get_current_job = original
            try:
                delattr(
                    printer,
                    "_klippervirtualsd_original_get_current_job"
                )
            except Exception:
                pass

    def _augment_virtual_sd_job(self, job):
        if not isinstance(job, dict):
            return job

        file_info = job.get("file")
        if not isinstance(file_info, dict):
            return job

        if file_info.get("origin") != "sdcard":
            return job

        path = file_info.get("path") or file_info.get("name")
        if not path:
            return job

        try:
            metadata = self._file_manager.get_metadata("local", path)
        except Exception:
            self._logger.debug(
                "No local metadata found for virtual-SD file %s",
                path,
                exc_info=True,
            )
            return job

        if not isinstance(metadata, dict):
            return job

        result = copy.deepcopy(job)
        result_file = result.setdefault("file", {})
        analysis = metadata.get("analysis")
        if not isinstance(analysis, dict):
            analysis = {}

        changed = []

        filament = analysis.get("filament")
        if filament is not None and not result.get("filament"):
            result["filament"] = copy.deepcopy(filament)
            changed.append("filament")

        estimated = analysis.get("estimatedPrintTime")
        if estimated is None:
            estimated = analysis.get("analysisPrintTime")

        if estimated is not None and result.get("estimatedPrintTime") is None:
            result["estimatedPrintTime"] = estimated
            changed.append("estimatedPrintTime")

        date = metadata.get("date")
        if date is None:
            date = metadata.get("modified")
        if date is None:
            try:
                local_path = self._file_manager.path_on_disk("local", path)
                date = int(os.path.getmtime(local_path))
            except Exception:
                date = None

        if date is not None and result_file.get("date") is None:
            result_file["date"] = date
            changed.append("date")

        if result_file.get("size") is None:
            try:
                local_path = self._file_manager.path_on_disk("local", path)
                result_file["size"] = os.path.getsize(local_path)
                changed.append("size")
            except Exception:
                pass

        if changed:
            self._logger.debug(
                "Augmented virtual-SD job %s with local metadata: %s",
                path,
                ", ".join(changed),
            )

        return result

    # ----------------------------------------------------------------------
    # Current-data compatibility layer
    # ----------------------------------------------------------------------
    def _install_current_data_alias(self):
        printer = self._printer
        if hasattr(printer, "_klippervirtualsd_original_get_current_data"):
            return

        original = printer.get_current_data
        printer._klippervirtualsd_original_get_current_data = original

        def augmented_get_current_data(*args, **kwargs):
            data = original(*args, **kwargs)
            try:
                if not isinstance(data, dict):
                    return data

                result = copy.deepcopy(data)
                if isinstance(result.get("job"), dict):
                    result["job"] = self._augment_virtual_sd_job(
                        result["job"]
                    )
                return result
            except Exception:
                self._logger.exception(
                    "Could not augment virtual-SD current data"
                )
                return data

        printer.get_current_data = augmented_get_current_data
        self._logger.info(
            "Installed current-data metadata augmentation for virtual SD"
        )

    def _remove_current_data_alias(self):
        printer = getattr(self, "_printer", None)
        if not printer:
            return

        original = getattr(
            printer, "_klippervirtualsd_original_get_current_data", None
        )
        if original:
            printer.get_current_data = original
            try:
                delattr(
                    printer,
                    "_klippervirtualsd_original_get_current_data"
                )
            except Exception:
                pass

    # ----------------------------------------------------------------------
    # UI/API
    # ----------------------------------------------------------------------
    def get_assets(self):
        return dict(js=["js/klippervirtualsd.js"])

    def get_api_commands(self):
        return {"print": ["path"]}

    def on_api_command(self, command, data):
        if command != "print":
            return flask.make_response("Unknown command", 400)

        path = data.get("path")
        if not path:
            return flask.make_response("Missing path", 400)

        if not self._printer.is_operational():
            return flask.make_response(
                "Printer is not operational", 409
            )

        if self._printer.is_printing() or self._printer.is_paused():
            return flask.make_response(
                "A print job is already active", 409
            )

        try:
            self._printer.select_file(
                path,
                sd=True,
                printAfterSelect=True,
                tags={"source:plugin", "plugin:klippervirtualsd"},
            )
        except TypeError:
            self._printer.select_file(
                path, sd=True, printAfterSelect=True
            )
        except Exception as exc:
            self._logger.exception(
                "Could not start virtual-SD print"
            )
            return flask.make_response(str(exc), 500)

        return flask.jsonify(ok=True, path=path)

    # ----------------------------------------------------------------------
    # Klipper protocol adaptations
    # ----------------------------------------------------------------------
    def adapt_gcode_for_klipper(
        self,
        comm_instance,
        phase,
        cmd,
        cmd_type,
        gcode,
        subcode=None,
        tags=None,
        *args,
        **kwargs
    ):
        if not cmd:
            return None

        upper = cmd.strip().upper()

        if upper.startswith("M33"):
            return (None,)

        if upper == "M108":
            return (None,)

        if gcode == "M27" and self._printer.is_ready():
            return (None,)

        if gcode == "CANCEL_PRINT" and self._printer.is_cancelling():
            return ("SDCARD_RESET_FILE",)

        if gcode == "M26" and self._printer.is_cancelling():
            if upper.replace(" ", "") == "M26S0":
                return ("SDCARD_RESET_FILE",)

        return None


__plugin_name__ = "Klipper Virtual SD Print"
__plugin_version__ = "0.9.0"
__plugin_pythoncompat__ = ">=3.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = KlipperVirtualSDPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.comm.protocol.gcode.queuing":
            __plugin_implementation__.adapt_gcode_for_klipper,
    }
