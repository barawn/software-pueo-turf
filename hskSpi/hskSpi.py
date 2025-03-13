import struct
import spi
import selectors
from signalhandler import SignalHandler
from pathlib import Path
from gpio import GPIO
import logging
import argparse
import os
import pty
import itertools

EVENTPATH="/dev/input/by-path/platform-hsk-gpio-keys-event"
LOG_NAME="hskSpi"
PTYNAME = "/dev/hskspi"
LOG_LEVEL=logging.WARNING
CHUNKSIZE=32

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


class HskSPI(spi.SPI):
    def __init__(self, path='/dev/spidev2.0', gpiopin=79, speed=30000000, chunk_size=32):
        super().__init__(path)
        self.mode = self.MODE_0
        self.bits_per_word = 8
        self.speed = speed
        self.chunk_size = 32
        self.pin = GPIO(GPIO.get_gpio_pin(2, gpio_type='EMIO'), direction='in')

    def read(self):
        r = bytearray()
        while not self.complete:
            r += self.transfer(b'\x00'*self.chunk_size)
        return r
        
    @property
    def complete(self):
        return not self.pin.read()

    @staticmethod
    def find_device(compatstr):
        for dev in Path('/sys/bus/spi/devices').glob('*'):
            fullCompatible = (dev / 'of_node' / 'compatible').read_text().rstrip('\x00')
            if fullCompatible == compatstr:
                if ( dev / 'driver' ).exists():
                    ( dev / 'driver' / 'unbind' ).write_text(dev.name)
                (dev / 'driver_override').write_text('spidev')
                Path('/sys/bus/spi/drivers/spidev/bind').write_text(dev.name)
                devname = "/dev/spidev"+dev.name[3:]
                return devname
        return None    

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
    # Create the argument parser.
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('-p', '--pty', type=str, default=PTYNAME)
    parser.add_argument('-c', '--chunksize', type=int, default=CHUNKSIZE)
    # and parse arguments
    args = parser.parse_args()

    # Create the logger. Make first '-v' count double.
    if args.verbose:
        args.verbose += 1
    logLevel = LOG_LEVEL - 5*args.verbose
    addLoggingLevel('TRACE', logging.DEBUG - 5)
    addLoggingLevel('DETAIL', logging.INFO - 5)
    logger = logging.getLogger(LOG_NAME)
    logging.basicConfig(level=logLevel)
    
    # get the SPI device
    rdev = HskSPI(HskSPI.find_device('osu,turfhskRead'))

    # create the selector
    sel = selectors.DefaultSelector()

    # create the signal handler
    handler = SignalHandler(sel)

    # create pty and link it
    wpty, rpty = pty.openpty()
    rp = os.readlink(f"/proc/self/fd/{rpty}")
    if os.path.exists(args.pty) or os.path.islink(PTYNAME):
        os.remove(args.pty)
    os.symlink(rp, args.pty)
    logger.info("open with path " + args.pty)
    
    with open(EVENTPATH, "rb") as evf:
        def handlePacket(f, m):
            logger.trace("out of read wait")
            eb = f.read(Event.LENGTH)
            e = Event(eb)
            if e.code is None:
                logger.trace("received event separator")
            else:
                if e.code == 30 and e.value == 1:
                    logger.info("packet available: reading")
                    r = rdev.read()
                    logger.trace("read %d bytes" % len(r))
                    pkts = list(filter(None, r.split(b'\x00')))
                    logger.trace("found %d packets, forwarding" % len(pkts))
                    for pkt in pkts:
                        os.write(wpty, pkt+b'\x00')
                elif e.code == 30 and e.value == 0:
                    logger.trace("received read complete notification")

        # NEED TO ADD THE FUNCTION TO READ DATA FROM THE PTY TOO!
        sel.register(evf, selectors.EVENT_READ, handlePacket)
        
        while not handler.terminate:
            events = sel.select(timeout=0.1)
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)

    logger.info("exiting")
    os.close(wpty)
    os.close(rpty)
    os.remove(args.pty)
