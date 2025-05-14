# TURF software

The TURF software right now consists of 3 separate programs. Each
of these is running as a service in systemctl so there are
separate journals for each.

* pyturfHskd : 'main program', journal is under pueo-squashfs
* hskSpiBridge : connects and transfers Ethernet housekeeping data, journal is under hskspibridge
* hskRouter : collects and routes housekeeping data and responses, journal is under hskrouter

Each of these either has or will have an INI-style configuration script
(read with configparser). The __default__ configuration scripts are
stored in the squashfs, but they can be __overridden__ by placing
the INI file in the eMMC (which can be mounted via ``mnt /media``).
Please remember to unmount it, and ignore the fsck warning since it
always seems to be there.

The config files in the eMMC are copied to ``/usr/local/share`` so
you can also put files there (but they will not persist, obviously).
The config files do not need to be present - if they're not available
the program will just use their default config file in their directory.