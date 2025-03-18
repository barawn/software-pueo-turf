import os
import struct
import selectors
import signal
import logging
import queue

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

# let's collect our upstream/downstream interfaces
upstreams = []
downstreams = []

# create an upstream-to-downstream FIFO
packetsForDownstream = queue.Queue()
# create a downstream-to-upstream FIFO
packetsForUpstream = queue.Queue()

# create the handlers. We added the name parameter to just
# make things a bit easier to factor and debug

# true serial upstreams
for i in range(2):
    upstreams.append( SerHandler(sel,
                                 name="HSK"+str(i),
                                 logName=LOG_NAME,
                                 port='/dev/ttySC'+str(i),
                                 baud=460800) )
# ethernet upstream fakey serial
upstreams.append( SerHandler(sel,
                             name="SFC",
                             logName=LOG_NAME,
                             port='/dev/hskspi') )

# true serial downstreams
for i in range(4):
    downstreams.append( SerHandler(sel,
                                   name="TURFIO"+str(i),
                                   logName=LOG_NAME,
                                   port='/dev/ttyUL'+str(i),
                                   baud=500000) )

# start the upstreams
for uh in upstreams:
    # create a closure as the callback function
    def upstreamHandler(fd, mask):
        if uh.fifo.empty():
            logger.error("handler called but FIFO is empty?")
            return
        pktno = os.read(fd, 1)
        pkt = uh.fifo.get()
        packetsForDownstream.put(pkt)
        logger.info("got upstream packet #%d from %s via %s: %s",
                    pktNo[0],
                    hex(pkt[0]),
                    uh.name,
                    pkt.hex(sep=' '))
    uh.start(callback=upstreamHandler)
# start the downstreams
for dh in downstreams:
    # create a closure as the callback function
    def downstreamHandler(fd, mask):
        if dh.fifo.empty():
            logger.error("handler called but FIFO is empty?")
            return
        pktno = os.read(fd, 1)
        pkt = dh.fifo.get()
        packetsForUpstream.put(pkt)
        logger.info("got downstream packet #%d from %s via %s: %s",
                    pktNo[0],
                    hex(pkt[0]),
                    uh.name,
                    pkt.hex(sep=' '))
    dh.start(callback=downstreamHandler)
        
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

    # HOUSEKEEPING ROUTER!!
    while not packetsForDownstream.empty():
        pkt = packetsForDownstream.get()
        # just effing broadcast stuff downstream for now, we'll
        # worry about routing later.
        for dh in downstreams:
            dh.sendPacket(pkt)
    while not packetsForUpstream.empty():
        pkt = packetsForUpstream.get()
        logger.info("trying to find an upstream for destination %s",
                    hex(pkt[0]))
        for uh in upstreams:
            if pkt[0] in uh.sources:
                logger.info("forwarding packet to %s",
                            uh.name)
                uh.sendPacket(pkt)
                
logger.info("Terminating!")
upHskSerial.stop()

exit(0)
