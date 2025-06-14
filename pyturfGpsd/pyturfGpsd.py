#!/usr/bin/env python3

# this is not a gpsd
# it is amazingly dumb
from serial import Serial, SerialException
import pynmea2
import configparser
import logging
import os

from rawpty import RawPTY

LOG_NAME = "pyturfGpsd"
DEFAULT_CONFIG_NAME = "/usr/local/pylib/pyturfGpsd/pyturfGpsd.ini"
CONFIG_NAME = "/usr/local/share/pyturfGpsd.ini"

output_types = { 0 : lambda x : x.to_bytes(4,byteorder='little'),
                 1 : lambda x : str(x).encode() }

config = {}
config['LogLevel'] = logging.WARNING
config['GpsPath'] = '/dev/ttyPS1'
config['GpsBaud'] = 38400
config['PpsPath'] = '/dev/turfpps'
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
    
    pty = RawPTY(wellKnownName=config['PpsPath'])

    while True:
        try:
            line = gps.read_until(b'\r\n').strip(b'\r\n').decode()
            msg = pynmea2.parse(line)
            if type(msg) == pynmea2.RMC:
                tm = int(msg.datetime.timestamp())                
                os.write(pty.pty, formatter(tm))
        except SerialException as e:
            print(f'Device error: {repr(e)}')
            break
        except pynmea2.ParseError as e:
            print(f'NMEA parse error: {repr(e)}')
            continue
