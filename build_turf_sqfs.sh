#!/usr/bin/env bash

#########################################################
# BUILD THE pueo.sqfs FILE FOR THE TURF                 #
#########################################################

# sigh. yes, this whole setup is a giant mess.
# build_pueo_sqfs is for the SURF. it generates a pueo.sqfs for the SURF.
# build_turf_sqfs is for the TURF. it generates a pueo.sqfs for the TURF.
#
# at some point I thought all of this made sense

NECESSARY_SUBMODULES="pueo-utils \
		      pueo-python"
for p in ${NECESSARY_SUBMODULES} ; do
    if [ ! -f ${p}/README.md ] ; then
	echo "The ${p} submodule looks empty! Aborting!"
	exit 1
    fi
done


# boot script is magic, it will always rename to boot.sh
BOOTSCRIPT="boot_script/boot_pyturfhskd.sh"

# version script and file
VERSCRIPT="./create_pueo_sqfs_version.py"
VERFILE="PUEO_SQFS_VERSION"

# individual single-file python modules
PYTHON_SINGLE_FILES="pueo-utils/pysoceeprom/pysoceeprom.py \
	        pueo-utils/pyzynqmp/pyzynqmp.py \
		pueo-utils/signalhandler/signalhandler.py \
	      	sit5157/sit5157.py \
		rawpty/rawpty.py \
		pueo-utils/HskSerial/HskSerial.py"

# multi-file python modules wrapped in directories
PYTHON_DIRS="hskSpiBridge/ \
	     hskRouter/"

# scripts
SCRIPTS="pueo-utils/scripts/build_squashfs \
         pueo-utils/scripts/autoprog.py"

# binaries
# don't have any yet for TURF
#BINARIES=""

# name of the autoexclude file
THISEXCLUDE="pueo_sqfs_turf.exclude"

if [ "$#" -ne 1 ] ; then
    echo "usage: build_pueo_sqfs.sh <destination filename>"
    exit 1
fi

DEST=$1
WORKDIR=$(mktemp -d)

echo "Creating pueo.sqfs."
echo "Boot script is ${BOOTSCRIPT}."
cp ${BOOTSCRIPT} ${WORKDIR}/boot.sh

cp -R base_squashfs/* ${WORKDIR}
# now version the thing
$VERSCRIPT ${WORKDIR} ${VERFILE}

# autocreate the exclude
echo "... __pycache__/*" > ${WORKDIR}/share/${THISEXCLUDE}
for f in `find pueo-utils/python_squashfs -type f` ; do
    FN=`basename $f`
    FULLDIR=`dirname $f`
    DIR=`basename $FULLDIR`
    echo ${DIR}/${FN} >> ${WORKDIR}/share/${THISEXCLUDE}
done
# if build_squashfs is used there is no version!
# build_squashfs generates test software!
echo "share/version.pkl" >> ${WORKDIR}/share/${THISEXCLUDE}

if [ -z "${PYTHON_SINGLE_FILES}" ] ; then
    echo "No Python single files."
else
    for f in ${PYTHON_SINGLE_FILES} ; do
	cp $f ${WORKDIR}/pylib/
    done
fi

if [ -z "${PYTHON_DIRS}" ] ; then
    echo "No Python directories."
else
    for d in ${PYTHON_DIRS} ; do
	cp -R $d ${WORKDIR}/pylib/
    done
fi

# SURF build is special, it extracts stuff
echo "Building the TURF contents from pueo-python."
bash pueo-python/make_turf.sh ${WORKDIR}/pylib/

# pyturfHskd
if [ ! -e pyturfHskd/make_pyturfhskd.sh ] ; then
    echo "Skipping pyturfHskd"
else
    echo "Building pyturfHskd"
    bash pyturfHskd/make_pyturfhskd.sh ${WORKDIR}
fi

if [ -z "${SCRIPTS}" ] ; then
    echo "No scripts."
else 
    for s in ${SCRIPTS} ; do
	cp $s ${WORKDIR}/bin/
    done
fi

if [ -z "${BINARIES}" ] ; then
    echo "No binaries."
else
    for b in ${BINARIES} ; do
	cp $b ${WORKDIR}/bin/
    done
fi

# avoid gitignores and pycaches
mksquashfs ${WORKDIR} $1 -noappend -wildcards -ef pueo_sqfs.exclude
rm -rf ${WORKDIR}

echo "Complete."
