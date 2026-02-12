# TEK AFP Raspberry Pi Setup

This directory contains files for quick setup of a Raspberry Pi for a TEK AFP.

The script does the following:
- Installs runtime dependencies (namely PyVISA)
- Creates the group `afpusb`, adds the user to it, and creates udev rules for VISA usb access
- Enables the main UART (side effect: by default, bluetooth is disabled!)
- Changes the hostname to the format `tekafp-$SERIAL_NUMBER`
- Optionally installs development tools (uv) with the `-d` option

## Flashing
System media should be flashed with **RASPBERRY PI OS LITE (64-BIT)**

The easiest method is with the `rpi-imager` tool maintained by Raspberry Pi.

`rpi-imager` may prompt to ask "Would you like to apply OS customization settings?"
These will largely be overridden by the files `ssh`, `userconf.txt`, or after execution of `tek-afp-setup` script.

## Image Customizaton
After the imaging is complete, mount the `bootfs` partition and copy the files in this directory (`rpi-setup`) to it.
The media is now ready for the Pi to boot.

## After boot
The Pi will be accessible over ssh at the default port 22. 
The user is `tek`. Connect either to the ip (if known)
or to the hostname `tekafp-$SERIAL_NUMBER`.

| Credential    | Dev Default |
|---------------|-------------|
| user          | tek         |
| passwd        | team11      |
| serial number | 0           |

Use either ssh or a monitor and keyboard to log into the Pi
```bash
$ ssh tek@tekafp-0
```

Run the setup script (production)

```bash
$ /boot/firmware/tek-afp-setup
```

or (development)
```bash
$ /boot/firmware/tek-afp-setup -d
```

The script will ask to reboot. UART will not be enabled without a reboot.
The user must at least be logged out and back in for development tools and USB access.