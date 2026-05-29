# TEK AFP Raspberry Pi OS Image

This directory contains configuration for building custom images for the Raspberry Pi 4. The images
include all necessary libraries, configuration, services, and the AFP software. A flashed image
needs no extra setup: simply insert the microSD card into a Pi 4 and it will boot into the AFP interface.

The basics are covered below, and the AFP Developer Manual contains more detailed information.

## Building
The Makefile in the root of the repo has targets for building each part of the AFP.

* all: all
* ui: build the interface
* deb: package the built interface into a Debian package
* wheel: build the tekafp Python daemon
* image: build the full OS image. The UI's .deb and the wheel must be available in their default locations.


## Flashing
The easiest method is with the `rpi-imager` tool maintained by Raspberry Pi.

Or if you're brave, dd:

```bash
sudo dd if=image-builder/work/image-tek-afp-pi4/tek-afp-pi4
.img of=/dev/sda bs=4M conv=fsync status=progress
```

## After boot
The Pi will be accessible over ssh at the default port 22. 
The user is `tek`. Connect either to the ip (if known)
or to the hostname `tek-afp-$SERIAL_NUMBER`.

| Credential    | Default                    |
|---------------|----------------------------|
| user          | tek                        |
| passwd        | Team11Capstone!            |
| serial number | generated from MAC address |

If a display is available, the full hostname is displayed in the interface's "About" tab.

Use either ssh or a monitor and keyboard to log into the Pi
```bash
$ ssh tek@tek-afp-deadbeef
```

A handful of development tools are installed by default, such as vim and picocom.
