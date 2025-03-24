#!/usr/bin/env python3

# the housekeeping router spawns after the SPI bridge, although
# we might need to delay a bit to make sure /dev/hskspi is
# available.
import os, sys, time
import struct
import selectors
import signal
import logging
import queue
import configparser
from rawpty import RawPTY
from signalhandler import SignalHandler

# automagic
sys.path.append(os.path.dirname(__file__))
from turfSerHandler import SerHandler

LOG_NAME = "hskRouter"
CONFIG_NAME = "/usr/local/pylib/hskRouter/hskRouter.ini"

# configy stuff. just set up the dicts
config = {}
for i in range(4):
    config['TURFIO'+str(i)] = {}
    
if os.path.exists(CONFIG_NAME):
    parser = configparser.ConfigParser()
    parser.read(CONFIG_NAME)
    config['LogLevel'] = parser.getint('hskRouter', 'LogLevel', fallback=30)
    config['DownstreamTimeout'] = parser.getfloat('hskRouter', 'DownstreamTimeout', fallback=0.1)
    config['TurfSource'] = int(parser.get('hskRouter', 'TurfSource', fallback='0x60'), 0)
    config['TurfPath'] = parser.get('hskRouter', 'TurfPath', fallback='/dev/hskturf')
    for i in range(4):
        link = 'TURFIO'+str(i)
        config[link]['KnownSources'] = list(map(lambda x : int(x, 0),
                                                parser.get(link, 'KnownSources', fallback=[])))

# https://stackoverflow.com/questions/45455898/polling-for-a-maximum-wait-time-unless-condition-in-python-2-7
def wait_condition(condition, timeout=5.0, granularity=0.3, time_factory=time):
    end_time = time.time() + timeout   # compute the maximal end time
    status = condition()               # first condition check, no need to wait if condition already True
    while not status and time.time() < end_time:    # loop until the condition is false and timeout not exhausted
        time.sleep(granularity)        # release CPU cycles
        status = condition()           # check condition
    return status                      # at the end, be nice and return the final condition status : True = condition satisfied, False = timeout occurred.
        
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
logging.basicConfig(level=config['LogLevel'])

# wait a moment for hskspi to show up
if not wait_condition(lambda : os.path.exists('/dev/hskspi'),
                      timeout=1.0,
                      granularity=0.1):
    logger.error('/dev/hskspi did not show up - exiting!!')
    exit(1)

turfpty = RawPTY(config['TurfPath'])

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
# make an upstream handler factory function
# see e.g. https://eev.ee/blog/2011/04/24/gotcha-python-scoping-closures/
def makeUpstreamHandler(uph):
    def upstreamHandler(fd, mask):
        if uph.fifo.empty():
            logger.error("%s handler called but FIFO is empty?", uph.name)
            raise IOError("empty fifo read")            
        pktNo = os.read(fd, 1)
        pkt = uph.fifo.get()
        packetsForDownstream.put(pkt)
        logger.info("got upstream packet #%d from %s via %s: %s",
                    pktNo[0],
                    hex(pkt[0]),
                    uph.name,
                    pkt.hex(sep=' '))
    return upstreamHandler

# true serial downstreams
for i in range(4):
    downstreams.append( SerHandler(sel,
                                   name="TURFIO"+str(i),
                                   logName=LOG_NAME,
                                   downstream=True,
                                   knownSources=config['TURFIO'+str(i)]['KnownSources'],
                                   port='/dev/ttyUL'+str(i),
                                   baud=500000) )
# and add the fake TURF pty
th = SerHandler( sel,
                 name="TURF",
                 logName=LOG_NAME,
                 downstream=True,
                 knownSources=[config['TurfSource']],
                 port=None)
turfpty.serial_attach(th.port)
downstreams.append(th)

# make a downstream handler factory function
# see e.g. https://eev.ee/blog/2011/04/24/gotcha-python-scoping-closures/
def makeDownstreamHandler(downh):
    def downstreamHandler(fd, mask):
        if downh.fifo.empty():
            logger.error("%s handler called but FIFO is empty?", downh.name)
            return
        pktNo = os.read(fd, 1)
        pkt = downh.fifo.get()
        packetsForUpstream.put(pkt)
        logger.info("got downstream packet #%d from %s via %s: %s",
                    pktNo[0],
                    hex(pkt[0]),
                    downh.name,
                    pkt.hex(sep=' '))
    return downstreamHandler

# start the upstreams
for uh in upstreams:
    logger.info("starting %s handler", uh.name)
    uh.start(callback=makeUpstreamHandler(uh))

# start the downstreams
for dh in downstreams:
    logger.info("starting %s handler", dh.name)
    dh.start(callback=makeDownstreamHandler(dh))
        
while not handler.terminate:
    events = sel.select()
    for key, mask in events:
        callback = key.data
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
        dst = pkt[1]
        delivered = False
        for dh in downstreams:
            if dst in dh.sources:
                dh.sendPacket(pkt)
                delivered = True
        if not delivered:
            for dh in downstreams:
                dh.sendPacket(pkt)
    while not packetsForUpstream.empty():
        pkt = packetsForUpstream.get()
        dst = pkt[1]
        logger.info(f'trying to find an upstream for destination {hex(dst)}')
        for uh in upstreams:
            logger.trace(f'upstream {uh.name} has sources {uh.sources}')
            if dst in uh.sources:
                logger.info(f'forwarding packet to {uh.name}')
                uh.sendPacket(pkt)
                
logger.info("Terminating!")
for uh in upstreams:
    uh.stop()
for dh in downstreams:
    dh.stop()

os.remove(config['TurfPath'])

exit(0)
