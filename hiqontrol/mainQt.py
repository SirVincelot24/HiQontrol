import asyncio
import logging
import sys
from enum import Enum
from os import environ

from PySide6.QtCore import QSettings, Signal, QTimer
from PySide6.QtGui import Qt
from PySide6.QtWidgets import (QPushButton, QApplication,
                               QVBoxLayout, QDialog, QLabel, QHBoxLayout, QWidget, QSlider, QMainWindow)
from qasync import QEventLoop
from twisted.internet import asyncioreactor

import hiqnet
import soundcraft
from hiqnet.control import Control

APPNAME = 'HiQontrol'
on_rtd = environ.get('READTHEDOCS') == 'True'
SI_IMPACT_IP = '192.168.178.33'
SI_IMPACT_DEVICE_ADDRESS = 30850
SI_IMPACT_SERIAL = b'\x53\x69\x49\x6d\x70\x61\x63\x74\x38\x32\x37\x38\x38\x32\x00\x00'

logging.basicConfig(level=logging.INFO,
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


class ChannelStrip(QWidget):
    channel_name: str = ""
    button_state: ButtonState = ButtonState.ON

    state_changed = Signal(bool)

    def __init__(self, channel_name="", parent=None):
        super(ChannelStrip, self).__init__(parent)
        self.channel_name = channel_name
        # Create widgets
        self.name_label = QLabel(self.channel_name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.button = QPushButton("ON")
        self.button.setCheckable(True)
        self.button.setChecked(True)
        self.volume_slider = QSlider(Qt.Orientation.Vertical)

        # Create layout and add widgets
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label)
        layout.addWidget(self.button)
        layout.addWidget(self.volume_slider)
        # Set dialog layout
        self.setLayout(layout)
        self.button.clicked.connect(self.toggle_btn_state)
        self.set_btn_color()

    def toggle_btn_state(self):
        self.button_state = ButtonState.ON if self.button.isChecked() else ButtonState.OFF
        self.set_btn_color()
        self.state_changed.emit(self.button_state == ButtonState.ON)
        logger.info(f"State of Channel '{self.channel_name}' set to {self.button_state}")

    def set_btn_color(self):
        match self.button_state:
            case ButtonState.ON:
                self.button.setStyleSheet("background-color: green")
            case ButtonState.OFF:
                self.button.setStyleSheet("background-color: darkGray")
            case ButtonState.MUTED:
                self.button.setStyleSheet("background-color: red")


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

        for i in range(5):
            self.add_channel_strip(f"CH{i + 1}", ChannelStrip(f"CH{i + 1}"))

        self.add_channel_strip("PC", ChannelStrip("PC"))
        self.add_channel_strip("L & R", ChannelStrip("L & R"))

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
    except KeyError, TypeError:
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
                                       mixer_serial=SI_IMPACT_SERIAL)

        self.setCentralWidget(self.mixerWidget)

        reactor.listenTCP(hiqnet.service.ip.PORT, hiqnet.service.ip.Factory(self))
        reactor.listenUDP(hiqnet.service.ip.PORT, hiqnet.service.ip.UDPProtocol(self))
        reactor.listenUDP(soundcraft.ip.VUMETER_IP_PORT, soundcraft.ip.VuMeterUDPPRotocol(self))

        QTimer.singleShot(0, self.on_start)

    def on_start(self):
        """Initialize device and network communications."""
        self.control = Control(self.device, self.udp_transport, self.tcp_transport)
        self.mixerWidget.channel_strips["L & R"].state_changed.connect(self.control.toggle_lr_state)
        self.mixerWidget.channel_strips["PC"].state_changed.connect(lambda is_pressed: self.control.set_channel_state(
            is_pressed,
            object_address=b'\x00\x00\x15',
            channel_param=b'\x41'
        ))
        for i, channel_strip in enumerate(self.mixerWidget.channel_strips):
            if "CH" in channel_strip:
                param = bytes([i+1])
                self.mixerWidget.channel_strips[channel_strip].state_changed.connect(
                    lambda is_pressed, param=param: self.control.set_channel_state(
                        is_pressed,
                        object_address=b'\x00\x00\x15',
                        channel_param=param))
        self.control.disco_info(broadcast=True)
        # self.control.get_attributes()
        self.control.param_sub_all()
        self.control.multi_param_sub()


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

    logger.info("Application started")

    # Run the Qt/asyncio event loop.
    with loop:
        loop.run_forever()

    logger.info("Application stopped")
