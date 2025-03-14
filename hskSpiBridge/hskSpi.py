from pathlib import Path
import spi
from gpio import GPIO

class HskRSPI(spi.SPI):
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

class HskWSPI(spi.SPI):
    def __init__(self, path='/dev/spidev2.1', speed=30000000):
        super().__init__(path)
        self.mode = self.MODE_0
        self.bits_per_word = 8
        self.speed = speed
        self.chunk_size = 32
        self.pin = GPIO(GPIO.get_gpio_pin(2, gpio_type='EMIO'), direction='in')

    def write(self, pkt):
        self.transfer(pkt)

class HskSPI():
    @classmethod
    def spi_find_device(cls, compatstr):
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

    def __init__(self, speed=30000000):
        self.rspi = HskRSPI(self.spi_find_device('osu,turfhskRead'),
                            speed=speed)
        self.wspi = HskWSPI(self.spi_find_device('osu,turfhskWrite'),
                            speed=speed)
        self.read = self.rspi.read
        self.write = self.rspi.write
        
                            
