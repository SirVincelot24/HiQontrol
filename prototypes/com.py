#!/usr/bin/python
# *- coding: utf-8 -*
"""Prototype CLI communication using the hiqnet module"""

__author__ = 'Raphaël Doursenaud'

import logging
import socket

import hiqnet

from twisted.internet import reactor

try:
    import socketserver
except ImportError:
    # noinspection PyPep8Naming,PyUnresolvedReferences
    import SocketServer as socketserver

SI_COMPACT_16_IP = '192.168.178.33'
SI_COMPACT_16_DEVICE_ADDRESS = 30850  # 0x653

# TODO:add configuration for MY_DEVICE* parameters
MY_DEVICE_NAME = 'HiQontrolCLI'


def init_logging():
    """
    Initialize logging
    """
    l = logging.getLogger(__name__)
    l.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    ch.setFormatter(formatter)

    l.addHandler(ch)

    l.info('Initialized logging')

    return l


class App(object):
    """A dummy app to handle twisted callbacks."""
    udp_transport = None
    tcp_transport = None

    def __init__(self):
        pass

    def handle_message(self, *args):
        pass


if __name__ == '__main__':
    logger = init_logging()
    logger.info("RUN")

    my_device = hiqnet.device.Device(MY_DEVICE_NAME)

    logger.debug(my_device.network_info.mac_address)
    logger.debug(my_device.network_info.ip_address)
    logger.debug(my_device.network_info.subnet_mask)
    logger.debug(my_device.network_info.gateway_address)

    app = App()
    reactor.listenTCP(hiqnet.service.ip.PORT, hiqnet.service.ip.Factory(app))
    reactor.listenUDP(hiqnet.service.ip.PORT, hiqnet.service.ip.UDPProtocol(app))
    c = hiqnet.service.ip.Connection(app.udp_transport, app.tcp_transport)

    source_address = my_device.address
    destination_address = hiqnet.protocol.FullyQualifiedAddress.broadcast_address()  # Broadcast
    message = hiqnet.protocol.Command(source=source_address, destination=destination_address)
    message.disco_info(device=my_device)
    c.sendto(message)

    # destination_address = hiqnet.protocol.FullyQualifiedAddress(device_address=SI_COMPACT_16_DEVICE_ADDRESS)
    # message = hiqnet.protocol.Command(source=source_address, destination=destination_address)
    # message.hello()
    # c.sendto(message)

    destination_address = hiqnet.protocol.FullyQualifiedAddress(device_address=SI_COMPACT_16_DEVICE_ADDRESS)
    message = hiqnet.protocol.Command(source=source_address, destination=destination_address)
    message.get_vd_list()
    c.sendto(message)

    reactor.run()
