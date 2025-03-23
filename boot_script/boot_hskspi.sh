#!/bin/bash

# reload systemd to pick up our services
systemctl daemon-reload

# we have to program the FPGA first before services start
autoprog.py pysoceeprom.PySOCEEPROM

# The TURF has a few other daemons running on it
# automatically. List them here.
AUTO_SERVICES="hskspibridge"

for service in ${AUTO_SERVICES} ; do
    systemctl start $service
done

# fake it for now
PYTURFHSK="sleep infinity"

# dead duplicate of what's in pueo-squashfs
catch_term() {
    echo "termination signal caught"
    kill -TERM "$waitjob" 2>/dev/null
}

trap catch_term SIGTERM

# here's where pysurfHskd would run
$PYTURFHSK &
waitjob=$!

wait $waitjob
RETVAL=$?

for service in ${AUTO_SERVICES} ; do
    systemctl stop $service
done

exit $RETVAL
