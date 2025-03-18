import os
import struct
import selectors
import signal
import logging

from signalhandler import SignalHandler
from turfSerHandler import SerHandler

LOG_NAME = "test"

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

sel = selectors.DefaultSelector()
handler = SignalHandler(sel)

# spawn the upstream serial handler for testing
upHskSerial = SerHandler(sel,
                         logName=LOG_NAME,
                         port='/dev/ttySC0',
                         baud=460800)
# now let's try adding the Ethernet upstream 
upHskEth = SerHandler(sel,
                      logName=LOG_NAME,
                      port='/dev/hskspi')

def upHskEthHandler(fd, mask):
    if upHskEth.fifo.empty():
        logger.error("handler called but FIFO is empty?")
        return
    pktno = os.read(fd, 1)
    pkt = upHskEth.fifo.get()
    logger.info("got packet #%d from upHskEth:%s", pktno[0], pkt.hex(sep=' '))

def upHskSerialHandler(fd, mask):
    if upHskSerial.fifo.empty():
        logger.error("handler called but FIFO is empty?")
        return
    pktno = os.read(fd, 1)
    pkt = upHskSerial.fifo.get()
    logger.info("got packet #%d from upHskSerial:%s", pktno[0], pkt.hex(sep=' '))

upHskSerial.start(callback=upHskSerialHandler)
upHskEth.start(callback=upHskEthHandler)

while not handler.terminate:
    events = sel.select()
    for key, mask in events:
        callback = key.data
        logger.trace("processing %s", callback)
        try:
            callback(key.fileobj, mask)
        except Exception as e:
            import traceback
            logger.error("callback threw an exception: %s", repr(e))
            logger.error(traceback.format_exc())
            handler.set_terminate()

logger.info("Terminating!")
upHskSerial.stop()

exit(0)
