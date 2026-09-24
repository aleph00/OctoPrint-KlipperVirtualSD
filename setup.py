from setuptools import setup

setup(
    name="OctoPrint-KlipperVirtualSD",
    version="0.9.0",
    packages=["octoprint_klippervirtualsd"],
    package_data={
        "octoprint_klippervirtualsd": [
            "static/js/*.js",
            "templates/*.jinja2",
        ]
    },
    include_package_data=True,
    zip_safe=False,
    python_requires=">=3.7",
    entry_points={"octoprint.plugin": [
        "klippervirtualsd = octoprint_klippervirtualsd"
    ]},
)
