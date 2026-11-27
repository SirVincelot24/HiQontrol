import asyncio
import logging
import math
import struct
import sys
from argparse import ArgumentError
from enum import Enum
from os import environ

from PySide6.QtCore import QSettings, Signal, QTimer
from PySide6.QtGui import Qt, QIntValidator
from PySide6.QtWidgets import (QPushButton, QApplication,
                               QVBoxLayout, QLabel, QHBoxLayout, QWidget, QSlider, QMainWindow, QLineEdit)
from qasync import QEventLoop
from twisted.internet import asyncioreactor

import hiqnet
import soundcraft
from hiqnet.control import Control
from hiqnet.protocol import FullyQualifiedAddress

APPNAME = 'HiQontrol'
on_rtd = environ.get('READTHEDOCS') == 'True'
SI_IMPACT_IP = '192.168.178.33'
SI_IMPACT_DEVICE_ADDRESS = 30850
SI_IMPACT_SERIAL = b'\x53\x69\x49\x6d\x70\x61\x63\x74\x38\x32\x37\x38\x38\x32\x00\x00'

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    handlers=[
                        logging.StreamHandler(),
                        logging.FileHandler("app.log", encoding="utf-8")
                    ])
logger = logging.getLogger(__name__)


class ButtonState(Enum):
    OFF = 0
    ON = 1
    MUTED = 2


class ChannelType(Enum):
    MixerChannel = 0
    MixBus = 1
    MatrixBus = 2
    MasterBus = 3
    VCA = 4

class ChannelStrip(QWidget):
    """
    see godot implementation for the numbers
    """
    channel_name: str = ""
    button_state: ButtonState = ButtonState.ON
    object_address: bytes
    channel_id: int
    channel_type: ChannelType

    state_changed = Signal(bool, bytes, bytes)
    """
    state_changed = Signal(is_pressed, object_address, channel_param)
    """

    def __init__(self, channel_name, channel_type = ChannelType.MixerChannel, channel_id = 1, parent=None):
        super(ChannelStrip, self).__init__(parent)
        self.channel_name = channel_name
        match channel_type:
            case ChannelType.MixerChannel:
                self.object_address = b'\x00\x00\x15' # 0.0.21
            case ChannelType.MasterBus:
                self.object_address = b'\x00\x00\x02' # 0.0.2
            case ChannelType.MixBus:
                self.object_address = b'\x00\x00\x01' # 0.0.1
            case ChannelType.MatrixBus:
                self.object_address = b'\x00\x00\x01' # 0.0.1
            case ChannelType.VCA:
                self.object_address = b'\x00\x00\x42' # 0.0.66
            case _:
                raise ArgumentError(channel_type, f"channel type {channel_type} is invalid")
        self.channel_type = channel_type
        self.channel_id = channel_id
        # Create widgets
        self.name_label = QLabel(self.channel_name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.button = QPushButton("ON")
        self.button.setCheckable(True)
        self.button.setChecked(True)
        self.volume_slider = QSlider(Qt.Orientation.Vertical, tickPosition=QSlider.TickPosition.TicksBothSides)
        self.volume_slider.setRange(0, 1300)# -8832 to 640
        self.volume_slider.setValue(1000)
        self.volume_slider.valueChanged.connect(lambda value: self.volume_test_box.setText(str(fader_to_db(value))))
        self.volume_test_box = QLineEdit(text="0")
        self.volume_test_box.setValidator(QIntValidator(bottom=-8832, top=640))
        self.volume_set_btn = QPushButton("Send")

        # Create layout and add widgets
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label)
        layout.addWidget(self.button)
        layout.addWidget(self.volume_slider)
        layout.addWidget(self.volume_test_box)
        layout.addWidget(self.volume_set_btn)
        # Set dialog layout
        self.setLayout(layout)
        self.button.clicked.connect(self.toggle_btn_state)
        self.set_btn_color()

    def toggle_btn_state(self):
        self.button_state = ButtonState.ON if self.button.isChecked() else ButtonState.OFF
        self.set_btn_color()
        self.state_changed.emit(self.button_state == ButtonState.ON, self.object_address, self.channel_id)
        logger.info(f"State of Channel '{self.channel_name}' set to {self.button_state}")

    def set_btn_color(self):
        match self.button_state:
            case ButtonState.ON:
                self.button.setStyleSheet("background-color: green")
            case ButtonState.OFF:
                self.button.setStyleSheet("background-color: darkGray")
            case ButtonState.MUTED:
                self.button.setStyleSheet("background-color: red")

def fader_to_db(fader_value: int):
    min_val = -8832
    max_val = 640
    if fader_value <= 0: return min_val
    db_val = 20 * math.log10(fader_value / 1000)

    if fader_value < 1000:
        db_val *= 133
    else:
        db_val *= 281

    if db_val < min_val: return min_val
    if db_val > max_val: return max_val
    return int(db_val)

class MixerWidget(QWidget):
    mixer_ip: str
    mixer_device_address: int
    mixer_serial: bytes

    channel_strips: dict[str, ChannelStrip] = {}

    def __init__(self,
                 mixer_ip: str = SI_IMPACT_IP,
                 mixer_device_address=SI_IMPACT_DEVICE_ADDRESS,
                 mixer_serial=SI_IMPACT_SERIAL,
                 parent=None):
        super(MixerWidget, self).__init__(parent)
        self.mixer_ip = mixer_ip
        self.mixer_device_address = mixer_device_address
        self.mixer_serial = mixer_serial

        self.content_layout = QHBoxLayout()

        for i in range(1, 11):
            self.add_channel_strip(f"CH{i}", ChannelStrip(f"CH{i}", channel_id=i))

        self.add_channel_strip("PC", ChannelStrip("PC", channel_id=65, channel_type=ChannelType.MixerChannel))
        self.add_channel_strip("L & R", ChannelStrip("L & R", channel_id = 1, channel_type=ChannelType.MasterBus))

        self.setLayout(self.content_layout)

    def add_channel_strip(self, name: str, channel_strip: ChannelStrip):
        self.channel_strips[name] = channel_strip
        self.content_layout.addWidget(self.channel_strips[name])


class MainWindow(QMainWindow):
    datastore = QSettings()
    store_needs_update = False
    device = None
    logger.info("Initializing MainWindow")
    try:
        device_address = int(datastore.value('device_address'))
        device_name = str(datastore.value('device_name'))
        if device_address is None or device_name is None:
            raise KeyError
        device = hiqnet.device.Device(device_name, device_address)
        logger.info(f"Device '{device.name}' is connected")
    except (KeyError, TypeError):
        logger.warning(APPNAME + ': Settings not found, will use sane defaults')
        device_name = APPNAME
        device = hiqnet.device.Device(device_name)
        datastore.setValue('device_name', device.name)
        datastore.setValue('device_address', device.hiqnet_address)
    control = None
    udp_transport = None
    tcp_transport = None
    serial_number = SI_IMPACT_SERIAL  # FIXME get serial

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setWindowTitle("HiQontrol")

        self.mixerWidget = MixerWidget(mixer_ip=SI_IMPACT_IP, mixer_device_address=SI_IMPACT_DEVICE_ADDRESS,
                                       mixer_serial=self.serial_number)

        self.setCentralWidget(self.mixerWidget)

        # noinspection bad-argument-type
        reactor.listenTCP(hiqnet.service.ip.PORT, hiqnet.service.ip.Factory(self))
        reactor.listenUDP(hiqnet.service.ip.PORT, hiqnet.service.ip.UDPProtocol(self))
        reactor.listenUDP(soundcraft.ip.VUMETER_IP_PORT, soundcraft.ip.VuMeterUDPPRotocol(self))

        QTimer.singleShot(0, self.on_start)

    def on_start(self):
        """Initialize device and network communications."""
        self.control = Control(self.device, self.udp_transport, self.tcp_transport, self.mixerWidget.mixer_ip, self.mixerWidget.mixer_device_address)
        for channel_strip in self.mixerWidget.channel_strips:
            self.mixerWidget.channel_strips[channel_strip].state_changed.connect(self.control.set_channel_state)
            self.mixerWidget.channel_strips[channel_strip].volume_set_btn.clicked.connect(lambda _, channel_strip=channel_strip: self.on_volume_set(channel_strip))


        self.control.disco_info(broadcast=True, ip_address="255.255.255.255")
        self.control.disco_info(broadcast=True, ip_address="192.168.178.255")

    def on_volume_set(self, channel_name):
        channel_strip = self.mixerWidget.channel_strips[channel_name]
        channel_param: bytes
        match channel_strip.channel_type:
            case ChannelType.MixerChannel:
                channel_param = struct.pack("!H", channel_strip.channel_id + 72) # 1-72 are on/off switches
            case ChannelType.MasterBus:
                channel_param = struct.pack("!H", channel_strip.channel_id + 2) # 2 master buses
            case ChannelType.MixBus:
                channel_param = struct.pack("!H", channel_strip.channel_id + 18) # 14 mix buses + 4 matrix buses
            case ChannelType.MatrixBus:
                channel_param = struct.pack("!H", channel_strip.channel_id + 18 + 14) # (14 mix buses + 4 matrix buses) + 14 mix buses
            case ChannelType.VCA:
                channel_param = struct.pack("!H", channel_strip.channel_id + 8) # 8 VCAs
            case _:
                raise NotImplementedError
        self.control.multi_param_set_int(int(channel_strip.volume_test_box.text()),
                                         channel_param,
                                         FullyQualifiedAddress(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01',
                                                               object_address=channel_strip.object_address))

    def on_tcp_connected(self, transport):
        """Send all the parameter subscribe requests"""
        self.tcp_transport = transport
        self.control.tcp_transport = transport
        # self.control.get_attributes()
        self.control.param_sub_all(FullyQualifiedAddress(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=b'\x00\x00\x00'))
        self.control.param_sub_all(FullyQualifiedAddress(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=b'\x00\x00\x01'))
        self.control.param_sub_all(FullyQualifiedAddress(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=b'\x00\x00\x02'))
        self.control.param_sub_all(FullyQualifiedAddress(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=b'\x00\x00\x15'))
        self.control.param_sub_all(FullyQualifiedAddress(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=b'\x00\x00\x42'))
        self.control.param_sub_all(FullyQualifiedAddress(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=b'\x00\x00\x3e'))

        # self.control.multi_param_sub()

    def handle_message(self, message, host, protocol):
        """Handle messages received from twisted servers.

        Do nothing for debugging right now

        :param message: HiQnet message
        :type message: hiqnet.protocol.Command
        :param host: IPv4 host address
        :param protocol: Protocol that received
        :type protocol: str
        :return:
        """
        # if (message.message.name == "DISCOINFO" and
        #         str(message.destination_address) == str(FullyQualifiedAddress.broadcast_address())):
        #     self.control.disco_info()
        #     print(message.destination_address)
        #     print(FullyQualifiedAddress.broadcast_address())
        #     print("DISCOINFO!!!!!")
        #     pass
        # logger.debug(protocol + '(' + str(host) + ')' + str(binascii.hexlify(bytes(message))))

if __name__ == '__main__':
    # Create the Qt Application
    app = QApplication(sys.argv)

    # Create the Qt-backed asyncio event loop.
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Install Twisted's asyncio reactor BEFORE importing
    # twisted.internet.reactor anywhere else.
    asyncioreactor.install(loop)

    from twisted.internet import reactor

    # Create and show the window
    window = MainWindow()
    window.show()

    with open("style.qss" ,"rt") as f:
        _stylesheet = f.read()
        app.setStyleSheet(_stylesheet)

    logger.info("Application started")

    # Run the Qt/asyncio event loop.
    with loop:
        loop.run_forever()

    logger.info("Application stopped")
