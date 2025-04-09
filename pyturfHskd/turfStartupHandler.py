from enum import Enum
import logging
import os
from pueo.common.bf import bf
from pueo.common.uspeyescan import USPEyeScan
from threading import Lock

# the startup handler actually runs in the main
# thread. it either writes a byte to a pipe to
# indicate that it should be called again,
# or it pushes its run function into the tick FIFO
# if it wants to be called when the tick FIFO
# expires.
# the tick FIFO takes closures now
# god this thing is a headache
class TurfStartupHandler:

    class StartupState(int, Enum):
        STARTUP_BEGIN = 0
        STARTUP_END = 254
        STARTUP_FAILURE = 255

        def __index__(self) -> int:
            return self.value

    def __init__(self,
                 logName,
                 turfDev,
                 autoHaltState,
                 tickFifo):
        self.state = self.StartupState.STARTUP_BEGIN
        self.logger = logging.getLogger(logName)
        self.turf = turfDev
        self.endState = autoHaltState        
        self.tick = tickFifo
        self.rfd, self.wfd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.endState is None:
            self.endState = self.StartupState.STARTUP_BEGIN

        self.gbe_scan = SlowEyeScan('GBE', self.turf.gbe, self.logger)
        self.aurora_scan = SlowEyeScan('AUR', self.turf.aurora, self.logger)
        
    def _runNextTick(self):
        if not self.tick.full():
            self.tick.put(self.run)
        else:
            raise RuntimeError("tick FIFO became full in handler!!")

    def _runImmediate(self):
        toWrite = (self.state).to_bytes(1, 'big')
        nb = os.write(self.wfd, toWrite)
        if nb != len(toWrite):
            raise RuntimeError("could not write to pipe!")
        
    def run(self):
        # whatever dumb debugging
        self.logger.trace("startup state: %s", self.state)
        # endState is used to allow us to single-step
        # so if you set startup to 0 in the EEPROM, you can
        # set the end state via HSK and single-step through
        # startup.
        if self.state == self.endState or self.state == self.StartupState.STARTUP_FAILURE:
            # once we're in our end state we start running the eye scanner
            self.gbe_scan.tick()
            self.aurora_scan.tick()
            self._runNextTick()
            return
        elif self.state == self.StartupState.STARTUP_BEGIN:
            id = self.turf.read(0).to_bytes(4,'big')
            if id != b'TURF':
                self.logger.error("failed identifying TURF: %s", id.hex())
                self.state == self.StartupState.STARTUP_FAILURE
                self._runNextTick()
                return
            else:
                dv = self.turf.DateVersion(self.turf.read(0x4))
                self.logger.info("this is TURF %s", str(dv))
                self.state = self.StartupState.STARTUP_END
                self.gbe_scan.initialize()
                self.aurora_scan.initialize()
                self._runNextTick()
                return
        elif self.state == self.StartupState.STARTUP_END:
            self.gbe_scan.tick()
            self.aurora_scan.tick()
            self._runNextTick()
            return
        else:
            # keepalive
            self._runNextTick()

class SlowEyeScan:
    """ pass this a device which has a number of 'self.scanner' and a fn enableEyeScan """
    def __init__(self, name, dev, logger):
        self.name = name
        self.dev = dev
        self.state = [ None, None ]
        self.numScanners = len(self.dev.scanner)
        self.logger = logger

        verts = [ 96, 48, 0, -48, -96 ]
        horzs = [ -0.375, -0.1875, 0, 0.1875, 0.375 ]
        self.scan_seq = []
        for v in verts:
            for h in horzs:
                self.scan_seq.append( [ h, v ] )
        self.padding = b'\xff'*4 + b'\x00'*50
        self.currentResults = None
        self.workingResults = None
        self.workingScan = None
        self.resultsLock = Lock()

    def results(self):
        with self.resultsLock:
            return self.currentResults
        
    def initialize(self):
        self.logger.trace(f'{self.name} : initializing eye scan')
        # this is now safe in the sense that it should not reset
        # the link if the eye scan was already enabled
        self.setupLinks = self.dev.enableEyeScan()
        self.state = [ None, None ]
        
    def setNextChannelAndGetPadding(self):
        """ Find the next active channel and return any padding. """
        r = b''
        ch = self.state[0]
        if ch is None:
            ch = 0
        else:
            ch = ch + 1
        while ch < self.numScanners:
            up = self.dev.scanner[ch].up()
            setup = self.setupLinks[i]
            if up and setup:
                break
            else:
                if not up:
                    self.logger.debug(f'{self.name} : skipping channel {ch} since not up')
                else:
                    self.logger.info(f'{self.name} : channel {ch} is up now, but was not setup - skipping')
                r += self.padding
                ch = ch + 1
        if ch == self.numScanners:
            self.state[0] = None
        else:
            self.state[0] = ch
        return r

    def finish(self):
        with self.resultsLock:
            self.currentResults = self.workingResults
            # and reset back to start. we'll pick up next tick.
            self.state[0] = None
            self.state[1] = None
        
            
    def tick(self):
        if self.state[0] is None:
            self.logger.info(f'{self.name} : beginning a new scan')
            self.workingResults = self.setNextChannelAndGetPadding()
            if self.state[0] is None:
                # no up channels
                self.logger.debug(f'{self.name} : no active channels to scan')
                self.finish()
                return
            self.logger.debug(f'{self.name} : starting with channel {self.state[0]}')
            self.state[1] = 0
            self.workingScan = []
            ch = self.state[0]
            pt = self.scan_seq[0]
            self.dev.scanner[ch].horzoffset = pt[0]
            self.dev.scanner[ch].vertoffset = pt[1]
            self.dev.scanner[ch].prescale = 9
            self.dev.scanner[ch].start()
            return
        # ok we already were running. get the channel and point index
        ch = self.state[0]
        ptIdx = self.state[1]
        # if the scan isn't done, try next tick
        if not self.dev.scanner[ch].complete():
            return
        # scan was done, append the results
        self.workingScan.append(self.dev.scanner[ch].results())
        # move to next point
        self.state[1] = ptIdx + 1
        # are we past the last point?
        if not self.state[1] < len(self.scan_seq):
            self.logger.debug(f'{self.name}: channel {self.state[0]} complete')
            # yes, compress and store the results
            self.logger.trace(f'{self.name}: {self.workingScan}')
            cr = USPEyeScan.compress_results(self.workingScan)
            self.workingResults += cr
            self.workingResults += self.setNextChannelAndGetPadding()
            # are we past the last scanner?
            if self.state[0] is None:
                self.logger.info(f'{self.name}: scan complete')
                # yes, so complete, we'll start again next tick
                self.finish()
                return
            self.logger.trace(f'{self.name}: moving to channel {self.state[0]}')
            self.state[1] = 0
            self.workingScan = []

        pt = self.scan_seq[self.state[1]]
        ch = self.state[0]
        self.dev.scanner[ch].horzoffset = pt[0]
        self.dev.scanner[ch].vertoffset = pt[1]
        self.dev.scanner[ch].start()
            


                
