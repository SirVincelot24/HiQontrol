import hiqnet
from hiqnet.device import Device
from hiqnet.protocol import FullyQualifiedAddress

# from mainQt import SI_IMPACT_DEVICE_ADDRESS, SI_IMPACT_IP
SI_IMPACT_IP = '192.168.178.33'
SI_IMPACT_DEVICE_ADDRESS = 30850

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
        self.set_channel_state(is_pressed, object_address=b'\x00\x00\x02', channel_param=b'\x00\x01')

    def toggle_ch1_state(self, is_pressed: bool):
        self.set_channel_state(is_pressed, object_address=b'\x00\x00\x15', channel_param=b'\x00\x01')

    def multi_param_set_int(self, value: int, param_id: bytes, destination: FullyQualifiedAddress):
        c, message = self.init(destination.device_address, destination.vd_address, destination.object_address)
        message.multi_param_set_int(value, param_id)
        c.sendto(message, SI_IMPACT_IP)

    def set_channel_state(self, is_on: bool, object_address, channel_param):
        c, message = self.init(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=object_address)
        message.multi_param_set_bool(is_on, channel_param)
        c.sendto(message, SI_IMPACT_IP)

    def param_sub_all(self, destination_address: FullyQualifiedAddress):
        c, message = self.init(destination_address.device_address, destination_address.vd_address, destination_address.object_address)
        message.parameter_subscribe_all(self.source_device.hiqnet_address, destination_address.vd_address, destination_address.object_address)
        c.sendto(message, SI_IMPACT_IP)

    def multi_param_sub(self):
        c, message = self.init(SI_IMPACT_DEVICE_ADDRESS, vd_address=b'\x01', object_address=b'\x00\x00\x02')
        # message.multi_param_subscribe([(b'\x00\x01', self.source_device.address, b'\x00\x01', b'\x00\x00')])
        message.multi_param_subscribe([(1, self.source_device.address, 1, 0)])
        c.sendto(message, SI_IMPACT_IP)

    def get_attributes(self):
        c, message = self.init(SI_IMPACT_DEVICE_ADDRESS)
        message.get_attributes()
        c.sendto(message, SI_IMPACT_IP)

    def disco_info(self, broadcast:bool = False):
        c, message = self.init(65535 if broadcast else SI_IMPACT_DEVICE_ADDRESS)
        message.disco_info(self.source_device)
        c.sendto(message, SI_IMPACT_IP)
