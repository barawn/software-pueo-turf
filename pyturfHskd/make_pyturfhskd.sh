#!/bin/bash
# this script builds the desired portion of pyturfHskd
# in a target.

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

MAIN_FILE="pyturfHskd.py"

AUX_FILES="pueoTimer.py \
	   turfHskHandler.py \
	   turfHskProcessor.py \
           turfStartupHandler.py \
	   pyturfHskd.ini"

if [ "$#" -ne 1 ] ; then
    echo "usage: make_pyturfhskd.sh <destination directory>"
    echo "usage: (e.g. make_pyturfhskd.sh path/to/tmpsquashfs/pylib/ )"
    exit 1
fi

DEST=$1
mkdir -p $DEST/pyturfHskd

cp ${SCRIPT_DIR}/${MAIN_FILE} $DEST/pyturfHskd/
for f in ${AUX_FILES} ; do
    cp ${SCRIPT_DIR}/$f $DEST/pyturfHskd/
done
