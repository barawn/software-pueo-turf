#!/usr/bin/env python3

import struct
import spi
import selectors
import logging
import os
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

if os.path.exists(nm)
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


if __name__ == "__main__":
    addLoggingLevel('TRACE', logging.DEBUG - 5)
    addLoggingLevel('DETAIL', logging.INFO - 5)
    logger = logging.getLogger(LOG_NAME)
    logging.basicConfig(level=config['LogLevel'])
    
    # get the SPI device
    dev = HskSPI(chunk_size=config['ChunkSize'])

    # create the selector
    sel = selectors.DefaultSelector()

    # create the signal handler
    handler = SignalHandler(sel)

    # create pty.
    pty = RawPTY(wellKnownName=config['HskPath'])

    with open(EVENTPATH, "rb") as evf:
        def handleDownstream(f, m):
            logger.info("downstream packet available: reading")
            # data on pty
            r = os.read(pty.pty, 2048)
            logger.trace("read %d bytes" % len(r))
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
                    logger.trace("read %d bytes" % len(r))
                    pkts = list(filter(None, r.split(b'\x00')))
                    logger.trace("found %d packets, forwarding" % len(pkts))
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
