#!/usr/bin/env python3

import struct
import spi
import selectors
import logging
import os
from pathlib import Path
import sys
import configparser
from rawpty import RawPTY
from signalhandler import SignalHandler

# hskspi is hiding in our path, so fetch it
sys.path.append(os.path.dirname(__file__))
from hskSpi import HskSPI

EVENTPATH="/dev/input/by-path/platform-hsk-gpio-keys-event"
LOG_NAME="hskSpi"
DEFAULT_CONFIG_NAME = "/usr/local/pylib/hskSpiBridge/hskSpiBridge.ini"
CONFIG_NAME = "/usr/local/share/hskSpiBridge.ini"

config = {}
config['LogLevel'] = logging.WARNING
config['HskPath'] = "/dev/hskspi"
config['ChunkSize'] = 32

nm = DEFAULT_CONFIG_NAME
if os.path.exists(CONFIG_NAME):
    nm = CONFIG_NAME

if os.path.exists(nm):
    parser = configparser.ConfigParser()
    parser.read(nm)
    config['LogLevel'] = parser.getint('hskSpiBridge', 'LogLevel', fallback=config['LogLevel'])
    config['HskPath'] = parser.get('hskSpiBridge', 'HskPath', fallback=config['HskPath'])
    config['ChunkSize'] = parser.getint('hskSpiBridge', 'ChunkSize', fallback=config['ChunkSize'])

# https://stackoverflow.com/questions/2183233/how-to-add-a-custom-loglevel-to-pythons-logging-facility/35804945
def addLoggingLevel(levelName, levelNum, methodName=None):
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
       raise AttributeError('{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
       raise AttributeError('{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
       raise AttributeError('{} already defined in logger class'.format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)
    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)

# this is supertrimmed for PUEO
class Event:
    # ll = struct timespec, H=type, H=code, I=value
    FORMAT='llHHI'
    LENGTH=struct.calcsize(FORMAT)
    def __init__(self, data):
        vals = struct.unpack(self.FORMAT, data)
        if vals[2] != 0 or vals[3] != 0 or vals[4] != 0:
            self.code = vals[3]
            self.value = vals[4]
        else:
            self.code = None

PYFW = b'PYFW'
TMPPATH="/tmp/pyfwupd.tmp"

class UploadHandler:
    def __init__(self, l, h):
        self.logger = l
        self.handler = h
        self.pktno = 0
        self.curFile = None
        self.tmpPath = Path(TMPPATH)
        self.NULL = bytes(32)
        if self.tmpPath.exists():
            self.tmpPath.unlink()
        self.tempFile = open(self.tmpPath, "w+b")
        
    def handleUploadPacket(self, r):
        if r == self.NULL:
            self.logger.file(f'upload: reset/separator')
            # A 32-byte chunk of nothing but zeroes is a separator/reset.
            # Note that in the uploader we avoid triggering this by
            # making sure that all packets are 1024 bytes, and letting
            # the completion trim it.            
            if self.curFile:
                self.logger.info(f'upload: abandoning file {curFile[0]}')
                self.tempFile.close()
                self.tempFile = open(self.tmpPath, "w+b")
            self.pktno = 0
            return self.pktno        
        if self.curFile is None:
            # we don't need PYEXs in the TURF
            if r[1:5] != PYFW:
                self.logger.error(f'comm error: first packet {r[1:5].hex()}')
                return None
            self.logger.debug('upload: PYFW okay, unpacking header')
            thisLen = struct.unpack(">I", r[5:9])[0]
            endFn = r[9:].index(b'\x00')+9
            thisFn = r[13:endFn].decode()
            cks = sum(r[:endFn+2]) % 256
            if cks != 0:
                self.logger.error(f'upload: checksum failed: {r[:endFn+2].hex()}')
                return None
            self.logger.info(f'upload: beginning {thisFn} length {thisLen}')
            self.curFile = [ thisFn, thisLen ] 
            r = r[endFn+2:]
        else:
            r = r[1:]
        if len(r) > self.curFile[1]:
            try:
                self.tempFile.write(r[:self.curFile[1]])
                self.tempFile.close()
                shutil.move(self.tmpPath, self.curFile[0])
                md5 = filemd5(self.curFile[0])
                self.logger.file(f'upload: completed {self.curFile[0] : md5sum {md5}}')
                self.tempFile = open(self.tmpPath, "w+b")
            except Exception as e:
                """ this is bad """
                self.logger.error('upload: Finishing file failed: ' + repr(e))
                self.handler.set_terminate()
                return None
            self.curFile = None
        else:
            try:
                self.tempFile.write(r)
            except Exception as e:
                """ also bad """
                self.logger.error('upload: Writing to file failed: ' + repr(e))
                self.handler.set_terminate()
                return None
        self.pktno = (self.pktno + 1) & 0xFF
        return self.pktno
                                    
if __name__ == "__main__":
    addLoggingLevel('TRACE', logging.DEBUG - 5)
    addLoggingLevel('DETAIL', logging.INFO - 5)
    addLoggingLevel('FILE', 100)
    logger = logging.getLogger(LOG_NAME)
    logging.basicConfig(level=config['LogLevel'])
    
    # get the SPI device
    dev = HskSPI(chunk_size=config['ChunkSize'])
    # set the upload count to zero
    dev.upload_count = 0
    
    # create the selector
    sel = selectors.DefaultSelector()

    # create the signal handler
    handler = SignalHandler(sel)

    # create the upload handler
    upload = UploadHandler(logger, handler)
    
    # create pty.
    pty = RawPTY(wellKnownName=config['HskPath'])

    with open(EVENTPATH, "rb") as evf:
        def handleDownstream(f, m):
            logger.info("downstream packet available: reading")
            # data on pty
            r = os.read(pty.pty, 2048)
            logger.trace(f'read {len(r)} bytes')
            dev.write(r)
            
        def handleUpstream(f, m):
            # interrupt on SPI
            logger.trace("out of read wait")
            eb = f.read(Event.LENGTH)
            e = Event(eb)
            if e.code is None:
                logger.trace("received event separator")
            else:
                if e.code == 30 and e.value == 1:
                    logger.info("upstream packet available: reading")
                    r = dev.read(untilEmpty=True)
                    logger.trace(f'read {len(r)} bytes')
                    # handle uploads. uploads are indicated by null starting bytes
                    # and acked by the upload packet count
                    # you bound stuff by any housekeeping packet
                    # so like ePingPong/upload/ePingPong/upload/etc.
                    if r[0] == 0:
                        r = upload.handleUploadPacket(r)
                        if r is not None:
                            dev.write(r.to_bytes(1, 'big'))
                            return
                        else:
                            logger.error('weird upload packet discarded')
                            return
                    pkts = list(filter(None, r.split(b'\x00')))
                    logger.trace(f'found {len(pkts)} packets, forwarding')
                    for pkt in pkts:
                        os.write(pty.pty, pkt+b'\x00')
                elif e.code == 30 and e.value == 0:
                    logger.trace("received read complete notification")

        sel.register(evf, selectors.EVENT_READ, handleUpstream)
        sel.register(pty.pty, selectors.EVENT_READ, handleDownstream)
        
        while not handler.terminate:
            events = sel.select(timeout=0.1)
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)

    logger.info("exiting")
