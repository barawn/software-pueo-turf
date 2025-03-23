import os
import fcntl
from termios import *

# this is a bunch of random utilities for fake serial-port like things

# sigh. no tty.cfmakeraw on python 3.9
# Indices for termios list.
IFLAG = 0
OFLAG = 1
CFLAG = 2
LFLAG = 3
ISPEED = 4
OSPEED = 5
CC = 6

# I should try to find out if this function exists already...
def cfmakeraw(mode):
    """Make termios mode raw."""
    # Clear all POSIX.1-2017 input mode flags.
    # See chapter 11 "General Terminal Interface"
    # of POSIX.1-2017 Base Definitions.
    mode[IFLAG] &= ~(IGNBRK | BRKINT | IGNPAR | PARMRK | INPCK | ISTRIP |
                     INLCR | IGNCR | ICRNL | IXON | IXANY | IXOFF)

    # Do not post-process output.
    mode[OFLAG] &= ~OPOST

    # Disable parity generation and detection; clear character size mask;
    # let character size be 8 bits.
    mode[CFLAG] &= ~(PARENB | CSIZE)
    mode[CFLAG] |= CS8

    # Clear all POSIX.1-2017 local mode flags.
    mode[LFLAG] &= ~(ECHO | ECHOE | ECHOK | ECHONL | ICANON |
                     IEXTEN | ISIG | NOFLSH | TOSTOP)

    # POSIX.1-2017, 11.1.7 Non-Canonical Mode Input Processing,
    # Case B: MIN>0, TIME=0
    # A pending read shall block until MIN (here 1) bytes are received,
    # or a signal is received.
    mode[CC] = list(mode[CC])
    mode[CC][VMIN] = 1
    mode[CC][VTIME] = 0

# and a convenience class
class RawPTY:
    def __init__(self, wellKnownName):
        self.pty, self.slv = pty.openpty()
        self.path = wellKnownName
        mode = tcgetattr(self.slv)
        cfmakeraw(mode)
        tcsetattr(self.slv, TCSANOW, mode)
        rp = os.ttyname(self.slv)
        if os.path.exists(self.path) or os.path.islink(self.path):
            os.remove(self.path)
        os.symlink(rp, self.path)
        
    def __del__(self):
        os.unlink(self.path)
        
    def serial_attach(self, ser):
        """ Attach this pty to a Serial instance that was started with port=None """

        # we need to be nonblocking for Serial
        flag = fcntl.fcntl(self.pty, fcntl.F_GETFL)
        fcntl.fcntl(self.pty, fcntl.F_SETFL, flag | os.O_NONBLOCK)
        # hide ourselves inside Serial so we don't go away until it does
        ser.pty = self
        # set our fd to Serial's fd
        ser.fd = fd
        # set Serial to be open
        ser.is_open = True
        # create the abort pipes and set the read versions to nonblocking
        ser.pipe_abort_read_r, ser.pipe_abort_read_w = os.pipe()
        ser.pipe_abort_write_r, ser.pipe_abort_write_w = os.pipe()
        fcntl.fcntl(ser.pipe_abort_read_r, fcntl.F_SETFL, os.O_NONBLOCK)
        fcntl.fcntl(ser.pipe_abort_write_r, fcntl.F_SETFL, os.O_NONBLOCK)


