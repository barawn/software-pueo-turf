#!/usr/bin/env python3

import argparse
import socket
import sys

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read bytes from a named Unix socket.")
    parser.add_argument("path", help="Named socket path")
    parser.add_argument("nb", type=int, help="Number of bytes to read")
    parser.add_argument("--hex")
    
    args = parser.parse_args()

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as svr:
            svr.connect(args.path)
            data = svr.recv(args.nb)
            if args.hex:
                print(data.hex(sep=' '))
            else:
                print(data.decode())
    except Exception as e:
        print(f'Exception: {repr(e)}', file=sys.stderr)
