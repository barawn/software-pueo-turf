from tca9554 import TCA9554
from electronics.gateways import LinuxDevice

class TURFCAL:
    modes = { 'OFF' : 0x12,
              'INT_LO' : 0x13,
              'INT_MID' : 0x23,
              'INT_HI' : 0x43,
              'EXT_LO' : 0x15,
              'EXT_MID' : 0x25,
              'EXT_HI' : 0x45 }
    
    def __init__(self, gw):
        """
        Class representing the calibration functions
        of the TURF. Right now it only handles setting
        TURFCAL modes. Later we will likely also want
        to handle programming the internal function
        generation tools.
        """
        self.dev = TCA9554(gw, address=0x38)

    @staticmethod
    def turf_gateway():
        """
        Convenience function because on the TURF
        it's always LinuxDevice(1). So embed it here
        so you can do TURFCAL(TURFCAL.turf_gateway())
        """
        return LinuxDevice(1)
        
    @property
    def mode(self):
        if self.dev.configuration == 0xFF:
            return None
        return self.dev.output_port
                    
    @mode.setter
    def mode(self, value):
        if type(value) == str:
            value = self.modes[value]

        self.dev.output_port = value
        self.dev.configuration = 0


