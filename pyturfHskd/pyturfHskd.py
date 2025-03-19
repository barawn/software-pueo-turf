# steal buckets upon buckets of stuff from
# surf code

import os
import struct
import selectors
import signal
import queue
import logging
from pueoTimer import HskTimer
from signalhandler import SignalHandler

LOG_NAME = "pyturfHskd"

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
logging.basicConfig(level=10)

# create the selector first
sel = selectors.DefaultSelector()
# now create our tick FIFO
tickFifo = queue.Queue()

##########################################################################

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

###########################################################################

# The TURF housekeeping is more of a bridge, but we also have to check
# if packets are intended for us either way.

