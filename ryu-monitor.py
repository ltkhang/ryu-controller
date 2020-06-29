from operator import attrgetter

from ryu.app import simple_switch_13
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub


class SimpleMonitor13(simple_switch_13.SimpleSwitch13):

    def __init__(self, *args, **kwargs):
        super(SimpleMonitor13, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)
        self.history = {}

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
            hub.sleep(10)

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

        for k, v in self.history.items():
            self.logger.info('%s %8d %8d', k, v['rx'], v['tx'])





