# -*- coding: utf-8 -*-
"""HiQontrol: an attempt at building a free, open source, multi–platform ViSi Remote alternative."""

__author__ = 'Raphaël Doursenaud'

import binascii
import re
from os import environ

from hiqnet.device import Device
from hiqnet.protocol import FullyQualifiedAddress

if environ.get('ANDROID_APP_PATH'):
    environ['PYTHON_EGG_CACHE'] = environ.get('ANDROID_APP_PATH')

from kivy.support import install_twisted_reactor

if __name__ == '__main__':
    install_twisted_reactor()
    from twisted.internet import reactor

from kivy.app import App

from kivy.logger import Logger
from kivy.storage.jsonstore import JsonStore
from kivy.properties import ObjectProperty
from kivy.clock import Clock
from kivy.uix.screenmanager import ScreenManager, FallOutTransition
from kivy.uix.textinput import TextInput
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.properties import (
    BooleanProperty,
    NumericProperty,
    StringProperty,
)

import hiqnet
import soundcraft

on_rtd = environ.get('READTHEDOCS') == 'True'

# FIXME: this should not be hardcoded but autodetected
SI_IMPACT_IP = '192.168.178.33'
SI_IMPACT_DEVICE_ADDRESS = 30850
SI_IMPACT_SERIAL = b'\x53\x69\x49\x6d\x70\x61\x63\x74\x38\x32\x37\x38\x38\x32\x00\x00' # SiCompact

APPNAME = 'HiQontrol'


class ListLocateButton(Button):
    blinking = BooleanProperty(False)
    hiqnet_address = NumericProperty(0)
    ip_address = StringProperty("")
    serial_number = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # self.hiqnet_address = kwargs['hiqnet_address']
        # self.ip_address = kwargs['ip_address']
        # self.serial_number = kwargs['serial_number']

    def toggle_blinking(self):
        if self.blinking:
            self.blink_stop()
        else:
            self.blink_start()

    def blink_start(self):
        if self.blinking:
            return
        self.background_color = [1, 0, 0, 1]
        Clock.schedule_interval(self.change_color, .5)
        self.blinking = True

    def blink_stop(self):
        Clock.unschedule(self.change_color)
        self.blinking = False

    # noinspection PyUnusedLocal
    def change_color(self, *args):
        self.background_color = [
            0 if self.background_color[0] else 1,
            self.background_color[1],
            self.background_color[2],
            self.background_color[3],
        ]

    def on_release(self):
        app = App.get_running_app()

        if app.control is not None:
            app.locate_toggle(
                self.hiqnet_address,
                self.ip_address,
                self.serial_number
            )

    def on_parent(self, instance, parent):
        # Stop scheduled callbacks if this button is removed.
        if parent is None:
            self.blink_stop()


class ListInfoButton(Button):
    pass

class ListMixButton(Button):
    pass

class DeviceRow(RecycleDataViewBehavior, BoxLayout):
    text = StringProperty("")
    ip_address = StringProperty("")
    hiqnet_address = NumericProperty(0)
    is_selected = BooleanProperty(False)

    def refresh_view_attrs(self, rv, index, data):
        result = super().refresh_view_attrs(rv, index, data)
        self.index = index
        return result

    def select_device(self):
        rv = self.parent.parent
        rv.selected_index = self.index

        for i, item in enumerate(rv.data):
            item["is_selected"] = (i == self.index)

        rv.refresh_from_data()

    def show_info(self):
        app = App.get_running_app()
        app.screen.current_screen.ids.infos.open()

    def open_mixer(self):
        app = App.get_running_app()
        app.screen.transition = FallOutTransition()
        app.screen.current = "mix"

class DeviceList(RecycleView):
    selected_index = NumericProperty(-1)

class HiQNetAddressInput(TextInput):
    # FIXME: don't allow value of 0 or over 65535
    pat = re.compile('[^0-9]]')

    def insert_text(self, substring, from_undo=False):
        pat = self.pat
        s = re.sub(pat, '', substring)
        return super(HiQNetAddressInput, self).insert_text(s, from_undo=from_undo)


class Control(object):
    locate = False
    source_device: Device = None
    udp_transport = None
    tcp_transport = None

    def __init__(self, source_device, udp_transport, tcp_transport):
        self.source_device = source_device
        self.udp_transport = udp_transport
        self.tcp_transport = tcp_transport

    def init(self, hiqnet_dest, vd_address: bytes = None, object_address: bytes = None):
        c = hiqnet.service.ip.Connection(self.udp_transport, self.tcp_transport)
        source_address = self.source_device.address
        destination_address = hiqnet.protocol.FullyQualifiedAddress(device_address=hiqnet_dest, vd_address=vd_address, object_address=object_address)
        message = hiqnet.protocol.Command(source=source_address, destination=destination_address)
        return c, message

    def locate_toggle(self, hiqnet_dest, ip_dest, serial_dest):
        c, message = self.init(hiqnet_dest)
        if not self.locate:
            message.locate_on(serial_dest)
            self.locate = True
        else:
            message.locate_off(serial_dest)
            self.locate = False
        c.sendto(message, ip_dest)

    def toggle_lr_state(self, is_pressed: bool):
        c, message = self.init(30850, vd_address=b'\x01', object_address=b'\x00\x00\x02')
        message.multi_param_set(is_pressed)
        c.sendto(message, "192.168.178.33")

    def param_sub_all(self):
        c, message = self.init(30850, vd_address=b'\x01', object_address=b'\x00\x00\x02')
        message.parameter_subscribe_all(self.source_device.hiqnet_address)
        c.sendto(message, "192.168.178.33")

    def multi_param_sub(self):
        c, message = self.init(30850, vd_address=b'\x01', object_address=b'\x00\x00\x02')
        # message.multi_param_subscribe([(b'\x00\x01', self.source_device.address, b'\x00\x01', b'\x00\x00')])
        message.multi_param_subscribe([(1, self.source_device.address, 1, 0)])
        c.sendto(message, "192.168.178.33")

    def get_attributes(self):
        c, message = self.init(30850)
        message.get_attributes()
        c.sendto(message, "192.168.178.33")

    def disco_info(self, broadcast:bool = False):
        c, message = self.init(65535 if broadcast else 30850)
        message.disco_info(self.source_device)
        c.sendto(message, "192.168.178.33")


class HiQontrol(ScreenManager):
    list = ObjectProperty()


class HiQontrolApp(App):
    __version__ = '0.0.3'
    datastore = JsonStore('settings.json')
    store_needs_update = False
    device = None
    try:
        device = hiqnet.device.Device(datastore.get('device_name')['value'], datastore.get('device_address')['value'])
    except KeyError:
        Logger.warning(APPNAME + ': Settings not found, will use sane defaults')
        device_name = APPNAME
        device = hiqnet.device.Device(device_name)
        datastore.put('device_name', value=device.name)
        datastore.put('device_address', value=device.hiqnet_address)
    except TypeError:
        if on_rtd:
            pass
    control = None
    screen = None
    udp_transport = None
    tcp_transport = None
    serial_number = SI_IMPACT_SERIAL # FIXME get serial

    def build(self):
        reactor.listenTCP(hiqnet.service.ip.PORT, hiqnet.service.ip.Factory(self))
        reactor.listenUDP(hiqnet.service.ip.PORT, hiqnet.service.ip.UDPProtocol(self))
        reactor.listenUDP(soundcraft.ip.VUMETER_IP_PORT, soundcraft.ip.VuMeterUDPPRotocol(self))
        self.title = APPNAME
        self.icon = 'assets/icon.png'
        self.screen = HiQontrol(list=self.populate())
        return self.screen

    def on_start(self):
        """Initialize device and network communications."""
        self.control = Control(self.device, self.udp_transport, self.tcp_transport)
        self.control.disco_info(broadcast=True)
        #self.control.get_attributes()
        self.control.param_sub_all()
        self.control.multi_param_sub()

    def on_pause(self):
        """Enable pause mode."""
        return True

    def store_needs_udate(self):
        self.store_needs_update = True

    def store_update(self, name, address):
        if self.store_needs_update:
            Logger.info(APPNAME + ": Updating store")
            self.datastore.put('device_name', value=name)
            self.datastore.put('device_address', value=int(address))
            Logger.info(APPNAME + ": Store updated, reloading device")
            self.device = hiqnet.device.Device(self.datastore.get('device_name')['value'],
                                               self.datastore.get('device_address')['value'])
            self.control = Control(self.device, self.udp_transport, self.tcp_transport)
            self.store_needs_update = False

    def get_model(self):
        # FIXME: placeholder
        return "Si Compact 16"

    def get_name(self):
        # FIXME: placeholder
        return "Si Compact 16"

    def get_hiqnet_address(self):
        # FIXME: placeholder
        return str(SI_IMPACT_DEVICE_ADDRESS)

    def get_ip_address(self):
        # FIXME: placeholder
        return SI_IMPACT_IP

    def get_local_name(self):
        return self.device.manager.name_string

    def get_local_hiqnet_address(self):
        return str(self.device._hiqnet_address)

    def get_local_mac_address(self):
        return self.device.network_info.mac_address

    def get_local_dhcp_status(self):
        return self.device.network_info.dhcp

    def get_local_ip_address(self):
        return self.device.network_info.ip_address

    def get_local_subnet_mask(self):
        return self.device.network_info.subnet_mask

    def get_local_gateway(self):
        return self.device.network_info.gateway_address

    def locate_toggle(self, hiqnet_dest, ip_dest, serial_dest):
        self.control.locate_toggle(hiqnet_dest, ip_dest, serial_dest)

    def toggle_lr_state(self, widget):
        is_pressed = widget.state == "down"
        self.control.toggle_lr_state(is_pressed)
        print(is_pressed)

    def populate(self):
        # FIXME: Detect devices dynamically or allow manual management.
        integers_dict = {
            '0': {
                'text': 'Si Impact (hardcoded)',
                'ip_address': SI_IMPACT_IP,
                'hiqnet_address': SI_IMPACT_DEVICE_ADDRESS,
                'is_selected': False,
            },
            '1': {
                'text': 'Lool',
                'ip_address': '192.168.1.3',
                'hiqnet_address': 9999,
                'is_selected': False,
            },
        }

        return [
            {
                'text': rec['text'],
                'ip_address': rec['ip_address'],
                'hiqnet_address': rec['hiqnet_address'],
                'is_selected': rec['is_selected'],
            }
            for key, rec in sorted(integers_dict.items())
        ]

    def handle_message(self, message, host, protocol):
        """Handle messages received from twisted servers.

        Only display it on screen for debugging right now

        :param message: HiQnet message
        :type message: hiqnet.protocol.Command
        :param: host: IPv4 host address
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
        self.screen.debug.text = protocol + '(' + str(host) + ')' + str(binascii.hexlify(bytes(message)))

if __name__ == '__main__':
    HiQontrolApp().run()
