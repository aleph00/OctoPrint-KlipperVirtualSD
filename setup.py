from setuptools import setup

setup(
    name="OctoPrint-KlipperVirtualSD",
    version="0.8.1",
    packages=["octoprint_klippervirtualsd"],
    package_data={"octoprint_klippervirtualsd": ["static/js/*.js"]},
    include_package_data=True,
    zip_safe=False,
    python_requires=">=3.7",
    entry_points={"octoprint.plugin": [
        "klippervirtualsd = octoprint_klippervirtualsd"
    ]},
)
