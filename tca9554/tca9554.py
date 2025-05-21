from electronics.device import I2CDevice

class TCA9554(I2CDevice):
    def __init__(self, bus, address=0x20):
        super().__init__(bus, address)

    def read(self, addr):
        self.i2c_write(addr.to_bytes(1, 'big'))
        v = self.i2c_read(1)
        return v[0]

    def write(self, addr, value):
        v = addr.to_bytes(1, 'big') + value.to_bytes(1, 'big')
        self.i2c_write(v)

    @property
    def input_port(self):
        return self.read(0)

    @property
    def output_port(self):
        return self.read(1)

    @output_port.setter
    def output_port(self, value):
        self.write(1, value)

    @property
    def polarity(self):
        return self.read(2)

    @polarity.setter
    def polarity(self, value):
        self.write(2, value)

    @property
    def configuration(self):
        return self.read(3)

    @configuration.setter
    def configuration(self, value):
        self.write(3, value)
        
