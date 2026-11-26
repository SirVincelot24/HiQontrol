# -*- coding: utf-8 -*-
"""HiQnet IP communication."""

from __future__ import print_function

__author__ = 'Raphaël Doursenaud'

import binascii
from mainQt import logger
from twisted.internet import protocol
from twisted.internet.interfaces import IAddress

from ..protocol import Command

PORT = 3804  # IANA declared as IQnet. Go figure.


class Connection(object):
    """Handles HiQnet IP connection.

    .. warning:: Other connection types such as RS232, RS485 or USB are not handled yet.
    """
    udp_transport = None
    tcp_transport = None

    def __init__(self, udp_transport, tcp_transport):
        """Initiate a HiQnet IP connection over UDP and TCP.

        :param udp_transport: Twisted UDP transport
        :type udp_transport: twisted.internet.interfaces.IUDPTransport
        :param tcp_transport: Twisted TCP transport
        :type tcp_transport: twisted.internet.interfaces.ITCPTransport
        :return:
        """
        self.udp_transport = udp_transport
        self.tcp_transport = tcp_transport

    def sendto(self, command, destination='<broadcast>'):
        """Send command to the destination.

        :param command: Message to send
        :type command: Command
        :param destination: Destination IPv4 address or '<broadcast>'
        :type destination: str
        """
        if command.flags.guaranteed:
            # Send TCP message if the Guaranteed flag is set
            # noinspection PyArgumentList
            self.tcp_transport.write(bytes(command), (destination, PORT))
        else:
            # noinspection PyArgumentList
            self.udp_transport.write(bytes(command), (destination, PORT))
        logger.info("=>")  # DEBUG
        logger.info(vars(command))  # DEBUG

class TCPProtocol(protocol.Protocol):
    """HiQnet Twisted TCP protocol."""

    name = "HiQnetTCP"

    def __init__(self):
        print("DEBUG init in protocol")

    def connectionMade(self):
        """is called after protocol started listening."""
        print("DEBBUG connectionMade in protocol")
        self.factory.app.tcp_transport = self.transport

    def dataReceived(self, data):
        """Called when data is received.

        :param data: Received binary data
        :type data: bytearray
        """
        # FIXME: debugging output should go into a logger
        logger.info("<=")
        logger.info(self.name + " data:")
        logger.info(binascii.hexlify(data))
        command = Command(command=data)
        logger.info(vars(command))  # DEBUG

        # TODO: Process some more :)
        self.factory.app.handle_message(command, None, self.name)


class UDPProtocol(protocol.DatagramProtocol):
    """HiQnet Twisted UDP protocol."""

    name = "HiQnetUDP"

    def __init__(self, app):
        self.app = app

    def startProtocol(self):
        """Called after protocol started listening."""
        self.transport.setBroadcastAllowed(True)  # Some messages need to be broadcasted
        self.app.udp_transport = self.transport

    def datagramReceived(self, data, addr):
        """Called when data is received.

        :param data: Received binary data
        :type data: bytearray
        :param addr: IPv4 address and port of the sender
        :type addr: tuple
        """
        (host, port) = addr

        # FIXME: debugging output should go into a logger
        logger.debug("<=")
        logger.debug(self.name + "data:")
        logger.debug(binascii.hexlify(data))
        logger.debug("from ", end="")
        logger.debug(host, end="")
        logger.debug(":", end="")
        logger.debug(port)
        command = Command(command=data)
        logger.debug(vars(command))  # DEBUG

        # TODO: Process some more :)
        self.app.handle_message(command, host, self.name)


class Factory(protocol.Factory):
    """HiQnet Twisted Factory."""

    protocol = TCPProtocol

    def __init__(self, app):
        self.app = app

    def buildProtocol(self, addr: IAddress | None):
        return TCPProtocol()

    def startFactory(self):
        print(f"startFactory with app {self.app}")