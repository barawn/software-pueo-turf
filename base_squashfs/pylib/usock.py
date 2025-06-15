#!/usr/bin/env python3

import argparse
import socket
import sys
import os
import threading

# Dumb classes/functions for simple
# Unix socket behavior.
# Call the script for a command-line Unix socket client.

class UnixSocketBroadcaster:
    """ Threaded broadcast server for Unix sockets. """
    def __init__(self, path, logger):
        self.path = path
        self.logger = logger
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
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

def usock_read(path, nb, timeout=None, mode=socket.SOCK_STREAM):
    """ Read nb bytes from Unix socket at path. """
    with socket.socket(socket.AF_UNIX, mode) as svr:
        try:
            svr.settimeout(timeout)
            svr.connect(path)
            svr.settimeout(timeout)
            return svr.recv(nb)
        except TimeoutError:
            return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read bytes from a named Unix socket.")
    parser.add_argument("path", help="Named socket path")
    parser.add_argument("nb", type=int, help="Number of bytes to read")
    parser.add_argument("--hex", action="store_true", help="printout in hex")
    
    args = parser.parse_args()
    try:
        data = usock_read(args.path, args.nb)
        if args.hex:
            print(data.hex(sep=' '))
        else:
            print(data.decode())
    except Exception as e:
        print(f'Exception: {repr(e)}', file=sys.stderr)
