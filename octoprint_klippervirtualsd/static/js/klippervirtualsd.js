$(function () {
    if (OctoPrint.files && OctoPrint.files.get &&
        !OctoPrint.files._klipperVirtualSdOriginalGet) {
        OctoPrint.files._klipperVirtualSdOriginalGet = OctoPrint.files.get;
        OctoPrint.files.get = function(location, path, opts) {
            if (location === "sdcard") location = "local";
            return OctoPrint.files._klipperVirtualSdOriginalGet.call(
                OctoPrint.files, location, path, opts
            );
        };
    }

    function KlipperVirtualSDViewModel(parameters) {
        var self = this;
        self.onBeforePrintStart = function (callback, data) {
            if (!data || data.origin !== "local" || !data.path) return true;

            OctoPrint.simpleApiCommand(
                "klippervirtualsd", "print", {path: data.path}
            ).done(function () {
                new PNotify({
                    title: "Klipper Virtual SD",
                    text: "Impression lancée via virtual_sdcard : " + data.name,
                    type: "success", hide: true
                });
            }).fail(function (xhr) {
                new PNotify({
                    title: "Klipper Virtual SD",
                    text: "Impossible de lancer l'impression : " +
                          (xhr && xhr.responseText ? xhr.responseText : "Erreur inconnue"),
                    type: "error", hide: false
                });
            });
            return false;
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: KlipperVirtualSDViewModel,
        dependencies: []
    });
});
