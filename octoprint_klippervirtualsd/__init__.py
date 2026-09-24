import copy
import os

import flask
import octoprint.plugin


class KlipperVirtualSDPlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.SimpleApiPlugin,
):
    def on_after_startup(self):
        self._install_storage_alias()
        self._install_current_job_alias()
        self._install_current_data_alias()
        self._logger.info("KlipperVirtualSD 0.8.1 ready")

    def on_shutdown(self):
        self._remove_current_data_alias()
        self._remove_current_job_alias()
        self._remove_storage_alias()

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
    #
    # OctoPrint deliberately treats a firmware-SD job as origin="sdcard".
    # In our setup the "SD card" is really Klipper's virtual_sdcard and the
    # file still exists in OctoPrint's local storage.  OctoPrint therefore
    # loses the local analysis metadata (filament, estimated print time,
    # date...) when building /api/job.
    #
    # v0.7 augments get_current_job() for virtual-SD jobs using the already
    # existing local file metadata.  Plugins such as SpoolManager and
    # PrintJobHistory that ask OctoPrint for the current job then see the
    # same analysis information as for a normal local print.
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

        # Do not mutate OctoPrint's own cached object in place.
        result = copy.deepcopy(job)
        result_file = result.setdefault("file", {})
        analysis = metadata.get("analysis")
        if not isinstance(analysis, dict):
            analysis = {}

        changed = []

        # Filament analysis.  Standard OctoPrint G-code analysis normally
        # stores this as:
        #   {"tool0": {"length": <mm>, "volume": <cm3>}}
        filament = analysis.get("filament")
        if filament is not None and not result.get("filament"):
            result["filament"] = copy.deepcopy(filament)
            changed.append("filament")

        # Estimated print time.
        estimated = analysis.get("estimatedPrintTime")
        if estimated is None:
            # Some analyzers/plugins use this key.
            estimated = analysis.get("analysisPrintTime")

        if estimated is not None and result.get("estimatedPrintTime") is None:
            result["estimatedPrintTime"] = estimated
            changed.append("estimatedPrintTime")

        # Last modified timestamp.  Prefer metadata, otherwise use the real
        # local file stat.
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

        # Size is normally already supplied by the firmware-SD job, but fill
        # it if OctoPrint did not provide it.
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
    #
    # /api/job may be built from PrinterInterface.get_current_data() rather
    # than directly from get_current_job().  v0.8 therefore augments both
    # paths.  This is also useful for plugins which consume the state monitor
    # structure instead of calling get_current_job() themselves.
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
__plugin_version__ = "0.8.1"
__plugin_pythoncompat__ = ">=3.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = KlipperVirtualSDPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.comm.protocol.gcode.queuing":
            __plugin_implementation__.adapt_gcode_for_klipper,
    }
