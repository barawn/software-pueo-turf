from enum import Enum
import logging
import os
from pueo.common.bf import bf

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
                self._runNextTick()
                return
        elif self.state == self.StartupState.STARTUP_END:
            self._runNextTick()
            return
