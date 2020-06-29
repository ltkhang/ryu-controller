import os
import logging
import six

from ryu.lib import hub, alert
from ryu.base import app_manager
from ryu.controller import event


BUFSIZE = 1024
SOCKFILE = "/tmp/ids-ddos"


class EventAlert(event.EventBase):
    def __init__(self, msg):
        super(EventAlert, self).__init__()
        self.msg = msg


class IDSLib(app_manager.RyuApp):

    def __init__(self):
        super(IDSLib, self).__init__()
        self.name = 'idslib'
        self._set_logger()
        self.sock = None


    def start_socket_server(self):
        self._start_recv()

    def _recv_loop(self):
        self.logger.info("Unix socket start listening...")
        while True:
            data = self.sock.recv(BUFSIZE)
            if not not data:
                self.send_event_to_observers(EventAlert(data.decode('utf-8')))

    def _start_recv(self):
        if os.path.exists(SOCKFILE):
            os.unlink(SOCKFILE)

        self.sock = hub.socket.socket(hub.socket.AF_UNIX,
                                      hub.socket.SOCK_DGRAM)
        self.sock.bind(SOCKFILE)
        hub.spawn(self._recv_loop)
 
    def _set_logger(self):
        """change log format."""
        self.logger.propagate = False
        hdl = logging.StreamHandler()
        fmt_str = '[ids-ddos][%(levelname)s] %(message)s'
        hdl.setFormatter(logging.Formatter(fmt_str))
        self.logger.addHandler(hdl)