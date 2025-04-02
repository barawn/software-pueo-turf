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
#
# _damnit_, no, we need to do more. The issue is that with multiple
# upstreams we need to make sure we're not sending multiple packets
# that might cause SURFs to talk over each other.
#
# NEW PLAN: for downstream guys we start a writer thread and
# create a queue for outbound packets. When we send an outbound
# packet, we clear the event and then wait for the inbound
# readerthread to set the event, up to 0.1 ms, before sending
# the next packet.
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
                 name=None,
                 logName="testing",
                 port='/dev/ttySC0',
                 baud=460800,
                 downstream=False,
                 knownSources=None):
        self.selector = sel
        self.name = name
        self.logger = logging.getLogger(logName)
        self.fifo = queue.Queue()
        self.port = Serial(port, baud)
        self.handler = None
        self.transport = None
        self.downstream = downstream        
        self.sources = [] if not knownSources else knownSources
        self.logger.trace(f'{self.name} sources is at {hex(id(self.sources))}')
        
        def makePacketHandler():
            return SerPacketHandler(self.fifo,
                                    logName,
                                    self.addSource,
                                    self.name,
                                    self.downstream)

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
        if sid not in self.sources:
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
                 addSource=lambda x : None,
                 name=None,
                 downstream=False):
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
        self.downstream = downstream
        self.name = name
        if self.downstream:
            # create an event to signal that we got a response
            self.inPacketEvent = threading.Event()
            # create a queue for the writer thread
            self.downstreamWriteFifo = queue.Queue()
            self.send_packet = self.send_packet_downstream
        else:
            self.inPacketEvent = None
            self.send_packet = self.send_packet_upstream
        # we start off having no write thread
        self.writeThread = None
        
    def connection_made(self, transport):
        super(SerPacketHandler, self).connection_made(transport)
        if self.downstream:
            # create the write thread in a running state
            self.terminate = False
            self.writeThread = threading.Thread(target=self.downstream_thread_send_packet)
            self.writeThread.start()
        self.logger.info("opened port")

    def connection_lost(self, exc):
        if isinstance(exc, Exception):
            self.logger.error(f'{self.name} : port closed due to exception')            
            raise exc
        if self.writeThread:
            # stop the write thread. This might take a second (literally a second).
            self.terminate = True
            self.writeThread.join()
            self.writeThread = None
        self.logger.info("closed port")

    def handleErrorPacket(self, pkt, msg):
        with self._statisticsLock:
            self._errorPackets = self._errorPackets + 1
            errorPackets = self._errorPackets
        self.logger.error(msg+" #%d : %s ", errorPackets, pkt.hex(sep=' '))
        
    def handle_packet(self, packet):
        """ implement the handle_packet function """
        if len(packet) == 0:
            return
        try:
            pkt = cobs.decode(packet)
        except cobs.DecodeError:
            self.handleErrorPacket(packet, "COBS decode error")
            return
        # COBS decode ok. At this point just flag that we got something.
        if self.inPacketEvent:
            self.inPacketEvent.set()
            
        # COBS decode ok. Next check packet length
        # and checksum
        pktLen = len(pkt)
        if pktLen < 5:
            self.handleErrorPacket(pkt, "Packet too short")
            return
        if pkt[3] != pktLen-5:
            self.handleErrorPacket(pkt, "Length of data (%d) doesn't match expected" % (pktLen-5))
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
                self.logger.trace(f'{self.name}: add known source {hex(pkt[0])}')
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
        
    def send_packet_upstream(self, packet):
        """ send binary packet via COBS encoding if upstream link """
        d = cobs.encode(packet) + b'\x00'
        if self.transport:
            self.transport.write(d)
        with self._statisticsLock:
            self._sentPackets = self._sentPackets + 1

    def send_packet_downstream(self, packet):
        """ send binary packet via COBS encoding if downstream link """
        d = cobs.encode(packet) + b'\x00'
        if self.downstreamWriteFifo: 
            self.logger.trace("forwarding packet to write thread")           
            self.downstreamWriteFifo.put(d)

    def downstream_thread_send_packet(self):
        """ Worker thread for cases where we send downstream. """
        self.logger.trace("%s write thread starting", self.name)
        while not self.terminate:
            try:
                self.inPacketEvent.clear()
                d = self.downstreamWriteFifo.get(timeout=1)
                self.logger.trace("write thread: got packet to write to downstream")
                if self.transport:
                    self.transport.write(d)
                with self._statisticsLock:
                    self._sentPackets = self._sentPackets + 1
                self.inPacketEvent.wait(0.1)
                if self.inPacketEvent.is_set():
                    self.logger.trace("write thread: got response")
                else:
                    self.logger.trace("write thread: timed out")
            except queue.Empty:
                pass
                
            
    def statistics(self):
        """ Get the packet statistics """
        r = []
        with self._statisticsLock:
            r = [self._receivedPackets,
                 self._sentPackets,
                 self._errorPackets,
                 self._droppedPackets ]
        return list(map(self._mod, r))

