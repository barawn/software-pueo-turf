from .tca9554 import TCA9554

class TURFCAL:
    modes = { 'OFF' : 0x12,
              'INT_LO' : 0x13,
              'INT_MID' : 0x23,
              'INT_HI' : 0x43,
              'EXT_LO' : 0x15,
              'EXT_MID' : 0x25,
              'EXT_HI' : 0x45 }
    
    def __init__(self, gw):
        self.dev = TCA9554(gw, address=0x38)

    @property
    def mode(self, value):
        if type(value) == str:
            value = self.modes[value]

        self.output_port = value
        self.configuration = 0


