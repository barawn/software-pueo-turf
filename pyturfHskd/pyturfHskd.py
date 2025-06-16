#!/usr/bin/env python3

# steal buckets upon buckets of stuff from
# surf code

import os
import struct
import selectors
import signal
import queue
import logging

from electronics.gateways import LinuxDevice
from sit5157 import SiT5157
from gpio import GPIO

from pueoTimer import HskTimer
from signalhandler import SignalHandler
from turfHskHandler import TurfHskHandler
from turfHskProcessor import TurfHskProcessor
from turfStartupHandler import TurfStartupHandler

from pyzynqmp import PyZynqMP
from pueo.turf import PueoTURF

LOG_NAME = "pyturfHskd"
DEFAULT_CONFIG_NAME = "/usr/local/pyturfHskd/pyturfHskd.ini"
CONFIG_NAME = "/usr/local/share/pyturfHskd.ini"

# these are the General configs
generalConfig = {}
startupConfig = None

nm = DEFAULT_CONFIG_NAME
if os.path.exists(CONFIG_NAME):
    nm = CONFIG_NAME

if os.path.exists(nm):
    parser = configparser.ConfigParser()
    parser.read(nm)
    # we can grab the general ones ourselves
    generalConfig['LogLevel'] = parser.getint('General', 'LogLevel', fallback=logging.WARNING)
    generalConfig['EndState'] = parser.getint('General', 'EndState', fallback=TurfStartupHandler.StartupState.STARTUP_END)
    # the startup dude processes their own
    if parser.has_section('Startup'):
        startupConfig = parser['Startup']
                
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

addLoggingLevel('TRACE', logging.DEBUG-5)
addLoggingLevel('DETAIL', logging.INFO-5)
logger = logging.getLogger(LOG_NAME)
logging.basicConfig(level=generalConfig['LogLevel'])

# just blitz the TURFIOs first
for i in range(4):
    # defaults to zero
    rst = GPIO(GPIO.get_gpio_pin(12+i), 'out')
    rst.write(1)
    del rst

# create the selector first
sel = selectors.DefaultSelector()
# now create our tick FIFO
tickFifo = queue.Queue()

##########################################################################
# HOUSEKEEPING TIMER
#
# this is our callback function for the timer
def runTickFifo(fd, mask):
    tick = os.read(fd, 1)
    logger.trace("tick %d", tick[0])
    toDoList = []
    while not tickFifo.empty():
        toDoList.append(tickFifo.get())
    for task in toDoList:
        logger.trace("processing %s", task)
        try:
            task()
        except Exception as e:
            import traceback

            logger.error("callback threw an exception: %s", repr(e))
            logger.error(traceback.format_exc())

            handler.set_terminate()

timer = HskTimer(sel, callback=runTickFifo, interval=1)
###########################################################################

###########################################################################
# SIGNAL HANDLER
#

handler = SignalHandler(sel)

###########################################################################


###########################################################################
# HSK HANDLER

hsk = TurfHskHandler(sel,
                     logName=LOG_NAME)

###########################################################################

logger.info("starting up")

zynq = PyZynqMP()
turf = PueoTURF(PueoTURF.axilite_bridge(), 'AXI')
# make this parameterizable later
useThisClock = 0x62
logger.info(f'using clock {useThisClock:#0x}')
clk = SiT5157(LinuxDevice(1), useThisClock)
clk.enable = 1

clksel = GPIO(GPIO.get_gpio_pin(25, 'MIO'), 'out')
if useThisClock == 0x6A:
    clksel.write(1)
else:
    clksel.write(0)

###########################################################################
# STARTUP HANDLER
startup = TurfStartupHandler(LOG_NAME,
                             turf,
                             generalConfig['EndState'],
                             tickFifo,
                             cfg=startupConfig)
def runHandler(fd, mask):
    st = os.read(fd, 1)
    logger.trace("immediate run: handler in state %d", st[0])
    startup.run()
sel.register(startup.rfd, selectors.EVENT_READ, runHandler)
###########################################################################

timer.start()
processor = TurfHskProcessor(hsk,
                             zynq,
                             startup,
                             LOG_NAME,
                             handler.set_terminate,
                             plxVersionFile="/etc/petalinux/version",
                             versionFile="/usr/local/share/version.pkl")

hsk.start(callback=processor.basicHandler)

try:
    startup.run()
except Exception as e:
    import traceback
    logger.error("callback threw an exception: %s", repr(e))
    logger.error(traceback.format_exc())
    
    handler.set_terminate()

while not handler.terminate:
    events = sel.select()
    for key, mask in events:
        callback = key.data
        logger.trace(f'processing {callback}')
        try:
            callback(key.fileobj, mask)
        except Exception as e:
            import traceback

            logger.error("callback threw an exception: %s", repr(e))
            logger.error(traceback.format_exc())

            handler.set_terminate()

logger.info("Terminating!")
timer.cancel()
hsk.stop()
processor.stop()

# ok, this changed with plx 0.3.0's pueo-squashfs:
# there's only one termination option we can do (0x7E) - terminate no unmount
# plus we have 0x7F (reboot)
# we then have 5 restart combinations with pueo-squashfs
# 0: normal exit and restart (load next software, keep local changes)
# 1: hot restart (do not load next software, keep local changes)
# 2: normal exit, revert and restart (load next software, abandon local changes)
# 3: hot revert and restart (do not load next software, abandon local changes)
# 4: clean up and restart (restart from QSPI)
#
# this is implemented with 3 bitmasks and 2 magic numbers
# we have an additional bitmask which is for Our Eyes Only

# 0x01: bmKeepCurrentSoft
# 0x02: bmRevertChanges
# 0x04: bmCleanup
# 0x08: bmForceReprogram
# 0xFE: kTerminate
# 0xFF: kReboot
# note that eRestart checks if bit 7 is set: if it is,
# and the value is not one of kTerminate or kReboot, it is IGNORED.
if processor.restartCode:
    code = processor.restartCode
    if code & processor.bmMagicValue:
        code = code ^ processor.bmMagicValue        
    elif code & processor.bmForceReprogram:
        os.unlink(zynq.CURRENT)
        code = code ^ processor.bmForceReprogram
    exit(code)
exit(0)
