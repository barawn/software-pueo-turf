from electronics.device import I2CDevice
from time import sleep

class SiT5157(I2CDevice):
    rangeMap = { 0 : 6.25,
                 1 : 10,
                 2 : 12.5,
                 3 : 25,
                 4 : 50,
                 5 : 80,
                 6 : 100,
                 7 : 125,
                 8 : 150,
                 9 : 200,
                 10 : 400,
                 11 : 600,
                 12 : 800,
                 13 : 1200,
                 14 : 1600,
                 15 : 3200 }
    
    def __init__(self, bus, address=0x62):
        super().__init__(bus, address)
        self.rangeToCode = dict(zip(self.rangeMap.values(),
                                    self.rangeMap.keys()))

    def read(self, addr):
        self.i2c_write(addr)
        v = self.i2c_read(2)
        return (v[0] << 8) | (v[1])

    def write(self, addr, value):
        v = addr.to_bytes(1, 'big') + value.to_bytes(2, 'big')
        self.i2c_write(v)

    @property
    def enable(self):
        """ Output enable for the clock """
        return (self.read(1) >> 10) & 0x1

    @enable.setter
    def enable(self, v):
        r = self.read(1) & 0xFBFF
        if v:
            r = r | (1<<10)
        self.write(1, r)

    @property
    def frequencyControl(self):
        """ Frequency pull control (-33,554,432 to +33,554,431) """
        r0 = self.read(0)
        r1 = self.read(1) & 0x3FF
        return (r1 << 16) | r0        

    @frequencyControl.setter
    def frequencyControl(self, ctrl):
        r0 = ctrl & 0xFFFF
        rm = self.read(1) & 0xFC00
        r1 = ((ctrl >> 16) & 0x3FF) | rm
        self.write(0, r0)
        self.write(1, r1)
        
    @property
    def pullRange(self):
        """ Full scale (in ppm) of the frequency control """
        return self.rangeMap[self.read(2) & 0xF]

    @pullRange.setter
    def pullRange(self, pull):
        r = (self.read(2) & 0xFFF0) | self.rangeToCode[pull]
        self.write(2, r)
        
        
        
