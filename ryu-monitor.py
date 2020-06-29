from operator import attrgetter

from ryu.app import simple_switch_13
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
from simple_switch_13 import SimpleSwitch13

from ryu.app.wsgi import ControllerBase
from ryu.app.wsgi import rpc_public
from ryu.app.wsgi import websocket
from ryu.app.wsgi import WebSocketRPCServer
from ryu.app.wsgi import WSGIApplication
import json
import idslib

simple_switch_instance_name = 'simple_switch_api_app'
url = '/monitor/ws'


class SimpleMonitor13(SimpleSwitch13):

    _CONTEXTS = {
         'wsgi': WSGIApplication,
         'idslib': idslib.IDSLib,
         }


    def __init__(self, *args, **kwargs):
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)
        self.history = {}

        wsgi = kwargs['wsgi']
        wsgi.register(
            SimpleSwitchWebSocketController,
            data={simple_switch_instance_name: self},
        )
        self._ws_manager = wsgi.websocketmanager
        kwargs['_ws_manager'] = self._ws_manager
        super(SimpleMonitor13, self).__init__(*args, **kwargs)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(5)

    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        #req = parser.OFPFlowStatsRequest(datapath)
        #datapath.send_msg(req)

        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body

        for stat in sorted(body, key=attrgetter('port_no')):
            if str(stat.port_no) not in self.history:
                self.history[str(stat.port_no)] = {}
                self.history[str(stat.port_no)]['rx'] = 0
                self.history[str(stat.port_no)]['tx'] = 0
                self.history[str(stat.port_no)]['last_rx'] = 0
                self.history[str(stat.port_no)]['last_tx'] = 0
            if self.history[str(stat.port_no)]['last_rx'] != stat.rx_packets:
            	self.history[str(stat.port_no)]['rx'] = stat.rx_packets - self.history[str(stat.port_no)]['last_rx']
            	self.history[str(stat.port_no)]['last_rx'] = stat.rx_packets
            else:
                self.history[str(stat.port_no)]['rx'] = 0
                
            if self.history[str(stat.port_no)]['last_tx'] != stat.tx_packets:
            	self.history[str(stat.port_no)]['tx'] = stat.tx_packets - self.history[str(stat.port_no)]['last_tx']
            	self.history[str(stat.port_no)]['last_tx'] = stat.tx_packets
            else:
                self.history[str(stat.port_no)]['tx'] = 0

        total_rx = 0
        total_tx = 0
        for k, v in self.history.items():
            self.logger.info('%s %8d %8d', k, v['rx'], v['tx'])
            total_rx += v['rx']
            total_tx += v['tx']
        self._ws_manager.broadcast(json.dumps({'type': 'monitor', 'rx': total_rx, 'tx': total_tx}))


class SimpleSwitchWebSocketController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(SimpleSwitchWebSocketController, self).__init__(
            req, link, data, **config)
        self.simple_switch_app = data[simple_switch_instance_name]

    @websocket('simpleswitch', url)
    def _websocket_handler(self, ws):
        simple_switch = self.simple_switch_app
        simple_switch.logger.debug('WebSocket connected: %s', ws)
        rpc_server = WebSocketRPCServer(ws, simple_switch)
        rpc_server.serve_forever()
        simple_switch.logger.debug('WebSocket disconnected: %s', ws)




