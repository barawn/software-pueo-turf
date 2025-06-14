#!/usr/bin/env python3

# this is not a gpsd
# it is amazingly dumb
# and yet it takes A MONUMENTAL AMOUNT OF GODDAMN EFFORT
# LIKE EVERYTHING AAUUUUUGHHHH

from serial import Serial, SerialException
import pynmea2
import configparser
import logging
import socket
import os
import threading

# We don't want to use rawpty since it buffers.
# We want to use a named Unix socket.
# This also allows us to have multiple clients.

class UnixSocketBroadcaster:
    def __init__(self, path, logger):
        self.path = path
        self.logger = logger
        os.unlink(path)
        self.server = socket.socket(socket.AF_UNIX,
                                    socket.SOCK_STREAM)
        self.server.bind(path)
        self.terminate = False
        self.server_thread = threading.Thread(target=self._listen_thread)
        self.start = self.server_thread.start
        
        self.clients = []
        self.client_lock = threading.Lock()

    def stop(self):
        self.terminate = True
        self.server_thread.join()
        os.unlink(self.path)
        
    def _listen_thread(self):
        self.server.listen()
        while not self.terminate:
            client, address = self.server.accept()
            self.logger.info(f'New client: {address}')
            client.settimeout(0.2)
            with self.client_lock:
                self.clients.append((client,address))

    def broadcast(self, msg):
        with self.client_lock:
            failed_clients = []
            for ct in self.clients:
                client = ct[0]
                address = ct[1]
                try:
                    nb = client.send(msg)
                    if nb == 0:
                        raise Exception('Disconnected')
                except Exception as e:
                    self.logger.info(f'Client {address} exception {repr(e)}')
                    failed_clients.append(ct)
            for fc in failed_clients:
                self.logger.info(f'Removing client {fc[1]}')
                self.clients.remove(fc)

LOG_NAME = "pyturfGpsd"
DEFAULT_CONFIG_NAME = "/usr/local/pylib/pyturfGpsd/pyturfGpsd.ini"
CONFIG_NAME = "/usr/local/share/pyturfGpsd.ini"

output_types = { 0 : lambda x : x.to_bytes(4,byteorder='little'),
                 1 : lambda x : str(x).encode() }

config = {}
config['LogLevel'] = logging.WARNING
config['GpsPath'] = '/dev/ttyPS1'
config['GpsBaud'] = 38400
config['PpsPath'] = '/tmp/turfpps'
config['OutputType'] = 0

nm = DEFAULT_CONFIG_NAME
if os.path.exists(CONFIG_NAME):
    nm = CONFIG_NAME

if os.path.exists(nm):
    parser = configparser.ConfigParser()
    parser.read(nm)
    config['LogLevel'] = parser.getint('pyturfGpsd',
                                       'LogLevel',
                                       fallback=config['LogLevel'])
    config['GpsPath'] = parser.get('pyturfGpsd',
                                   'GpsPath',
                                   fallback=config['GpsPath'])
    config['GpsBaud'] = parser.getint('pyturfGpsd',
                                   'GpsBaud',
                                   fallback=config['GpsBaud'])
    config['PpsPath'] = parser.get('pyturfGpsd',
                                   'PpsPath',
                                   fallback=config['PpsPath'])
    config['OutputType'] = parser.getint('pyturfGpsd',
                                         'OutputType',
                                         fallback=config['OutputType'])

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

if __name__ == "__main__":
    addLoggingLevel('TRACE', logging.DEBUG-5)
    addLoggingLevel('DETAIL', logging.INFO-5)
    logger = logging.getLogger(LOG_NAME)
    logging.basicConfig(level=config['LogLevel'])

    ot = config['OutputType']
    if ot not in output_types:
        logger.error(f'Output type {ot} not understood: using 0')
        ot = 0
    formatter = output_types[ot]
    
    gps = Serial(config['GpsPath'], baudrate=config['GpsBaud'])

    server = UnixSocketBroadcaster(config['PpsPath'],
                                   logger)

    server.start()
    
    while True:
        try:
            line = gps.read_until(b'\r\n').strip(b'\r\n').decode()
            msg = pynmea2.parse(line)
            if type(msg) == pynmea2.RMC:                
                tm = int(msg.datetime.timestamp())                
                server.broadcast(formatter(msg))
        except SerialException as e:
            print(f'Device error: {repr(e)}')
            break
        except pynmea2.ParseError as e:
            print(f'NMEA parse error: {repr(e)}')
            continue
