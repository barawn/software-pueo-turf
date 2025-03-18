# kindof a copy of the pyHskHandler from SURF but lil diff
# our goal here is to be able to spawn this for both up and downstream
# ports.
#
# Literally all this guy does is receive a packet, validate
# that it's OK, and push it to a queue. No filtering, so that part
# gets dropped and the verification gets pushed into the packet handler.
#
# The one thing we _add_ here is a function to store source IDs.
# That will let us route stuff.
from serial.threaded import Packetizer, ReaderThread
import logging
import threading
import traceback
import queue
import os
import selectors
from cobs import cobs
from serial import Serial

class SerHandler:
    def __init__(self,
                 sel,
                 logName="testing",
                 port='/dev/ttySC0',
                 baud=460800):
        self.selector = sel
        self.logger = logging.getLogger(logName)
        self.fifo = queue.Queue()
        self.port = Serial(port, baud)
        self.handler = None
        self.transport = None
        self.sources = []        
        
        def makePacketHandler():
            return SerPacketHandler(self.fifo, logName, self.addSource)

        self.reader = ReaderThread(self.port, makePacketHandler)
        self.sendPacket = self.notRunningError
        self.statistics = self.notRunningError

    def start(self, callback=None):
        if not callback:
            callback = self.dumpPacket
        self.reader.start()
        transport, handler = self.reader.connect()
        self.handler = handler
        self.transport = transport
        self.sendPacket = self.handler.send_packet
        self.statistics = self.handler.statistics

        self.selector.register(handler.rfd,
                               selectors.EVENT_READ,
                               callback)

    def stop(self):
        self.sendPacket = self.notRunningError
        self.statistics = self.notRunningError
        self.handler = None
        self.transport = None
        self.reader.stop()

    def addSource(self, sid):
        self.sources.append(sid)
        
    @staticmethod
    def notRunningError(*args):
        raise RuntimeError("the housekeeping handler is not running")

    def dumpPacket(self, fd, mask):
        """ print out the received packet from the fifo """
        if self.fifo.empty():
            self.logger.error("dumpPacket called but FIFO is empty?")
            return
        pktno = os.read(fd, 1)
        pkt = self.fifo.get()
        self.logger.info("Pkt %d: %s", pktno[0], pkt.hex(sep=' '))

# generic-y handler. This one adds checksum verification
class SerPacketHandler(Packetizer):
    def __init__(self,
                 fifo,
                 logName='serPacketHandler',
                 addSource=lambda x : None):
        super(SerPacketHandler, self).__init__()
        self.rfd, self.wfd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.fifo = fifo
        self.logger = logging.getLogger(logName)
        self._statisticsLock = threading.Lock()

        self._receivedPackets = 0
        self._sentPackets = 0
        self._errorPackets = 0
        self._droppedPackets = 0
        self._mod = lambda x : x & 0xFF
        self.addSource = addSource
        
    def connection_mode(self, transport):
        super(SerPacketHandler, self).connection_made(transport)
        self.logger.info("opened port")

    def connection_lost(self, exc):
        if isinstance(exc, Exception):
            self.logger.info("port closed due to exception")
            raise exc
        self.logger.info("closed port")

    def handleErrorPacket(self, pkt, msg):
        with self._statisticsLock:
            self._errorPackets = self._errorPackets + 1
            errorPackets = self._errorPackets
        self.logger.error(msg+" #%d : %s ", errorPackets, packet.hex(sep=' '))
        
    def handle_packet(self, packet):
        """ implement the handle_packet function """
        if len(packet) == 0:
            return
        try:
            pkt = cobs.decode(packet)
        except cobs.DecodeError:
            self.handleErrorPacket(pkt, "COBS decode error")
            return        
        # COBS decode ok. Next check packet length
        # and checksum
        pktLen = len(pkt)
        if pktLen < 5:
            self.handleErrorPacket(pkt, "Packet too short")
            return
        if pkt[3] != pktLen-5:
            self.handleErrorPacket(pkt, "Length of data (%d) doesn't match expected" % pktLen-5)
            return
        if sum(pkt[4:]) % 256:
            self.handleErrorPacket(pkt, "Invalid checksum")
            return
        # it's ok
        if not self.fifo.full():
            with self._statisticsLock:
                curPkt = self._receivedPackets
                self._receivedPackets = self._receivedPackets + 1
            # extract the source ID and add it to the list of sources we've seen
            # except zero is a nono
            if pkt[0]:
                self.addSource(pkt[0])
            self.fifo.put(pkt)
            # write something to our selfpipe to wake up the main thread
            toWrite = (curPkt & 0xFF).to_bytes(1, 'little')
            nb = os.write(self.wfd, toWrite)
            # wtf
            if nb != 1:
                self.logger.error("could not write packet number %d to pipe!" %
                                  curPkt)
        else:
            with self._statisticsLock:
                self._droppedPackets = self._droppedPackets + 1
                droppedPackets = self._droppedPackets
            self.logger.error("packet FIFO is full: dropped packet count %d" %
                              droppedPackets)
        
    def send_packet(self, packet):
        """ send binary packet via COBS encoding """
        d = cobs.encode(packet) + b'\x00'
        if self.transport:
            self.transport.write(d)
        with self._statisticsLock:
            self._sentPackets = self._sentPackets + 1

    def statistics(self):
        r = []
        with self._statisticsLock:
            r = [self._receivedPackets,
                 self._sentPackets,
                 self._errorPackets,
                 self._droppedPackets ]
        return list(map(self._mod, r))

