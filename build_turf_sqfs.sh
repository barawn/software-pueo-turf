#!/usr/bin/env bash

# sigh. yes, this whole setup is a giant mess.
# build_pueo_sqfs is for the SURF. it generates a pueo.sqfs for the SURF.
# build_turf_sqfs is for the TURF. it generates a pueo.sqfs for the TURF.
#
# at some point I thought all of this made sense

# boot script is magic, it will always rename to boot.sh
BOOTSCRIPT="boot_script/boot_teststartup.sh"

# version script and file
VERSCRIPT="./create_pueo_sqfs_version.py"
VERFILE="PUEO_SQFS_VERSION"

# individual single-file python modules
PYTHON_SINGLE_FILES="pysoceeprom/pysoceeprom.py \
	        pyzynqmp/pyzynqmp.py \
		signalhandler/signalhandler.py"

# multi-file python modules wrapped in directories
PYTHON_DIRS="pyrfdc/pyrfdc/ \
	       s6clk/ "
# scripts
SCRIPTS="scripts/build_squashfs \
         scripts/autoprog.py \
	 pyfwupd/pyfwupd.py"

# binaries
BINARIES="binaries/xilframe"

# name of the autoexclude file
SURFEXCLUDE="pueo_sqfs_surf.exclude"

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
echo "... __pycache__/*" > ${WORKDIR}/share/${SURFEXCLUDE}
for f in `find python_squashfs -type f` ; do
    FN=`basename $f`
    FULLDIR=`dirname $f`
    DIR=`basename $FULLDIR`
    echo ${DIR}/${FN} >> ${WORKDIR}/share/${SURFEXCLUDE}
done
# if build_squashfs is used there is no version!
# build_squashfs generates test software!
echo "share/version.pkl" >> ${WORKDIR}/share/${SURFEXCLUDE}

for f in ${PYTHON_SINGLE_FILES} ; do
    cp $f ${WORKDIR}/pylib/
done
for d in ${PYTHON_DIRS} ; do
    cp -R $d ${WORKDIR}/pylib/
done

# SURF build is special, it extracts stuff
echo "Building the SURF contents from pueo-python."
bash pueo-python/make_surf.sh ${WORKDIR}/pylib/

# pysurfHskd is special because so much testing
echo "Building pysurfHskd"
bash pysurfHskd/make_pysurfhskd.sh ${WORKDIR}

for s in ${SCRIPTS} ; do
    cp $s ${WORKDIR}/bin/
done

for b in ${BINARIES} ; do
    cp $b ${WORKDIR}/bin/
done

# avoid gitignores and pycaches
mksquashfs ${WORKDIR} $1 -noappend -wildcards -ef pueo_sqfs.exclude
rm -rf ${WORKDIR}

echo "Complete."
