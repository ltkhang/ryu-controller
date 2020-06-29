from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
import idslib
import time
import json


TIME_THRESHOLD = 60
MAX_ATTACK = 10


class SimpleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        'idslib': idslib.IDSLib,
    }

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.idslib = kwargs['idslib']
        self._ws_manager =  kwargs['_ws_manager']
        self.idslib.start_socket_server()
        self.counter = {}

        self.datapath_list = {}
        

    def concat_flow(self, ip_list):
        flow = ''
        for ip in ip_list:
            flow += ip + '-'
        return flow

    def process_msg(self, msg):
        self.logger.info(msg)
        ip_list = msg.split('-')
        if len(ip_list) == 2:
            ip_list.sort()
            flow = self.concat_flow(ip_list)
            if flow not in self.counter:
                self.counter[flow] = {}
                self.counter[flow]['first_time'] = time.time()
                self.counter[flow]['count'] = 0
            self.counter[flow]['count'] += 1

        current_time = time.time()
        deleted_flow = []
        for  flow, value in self.counter.items():
            if current_time - value['first_time'] > TIME_THRESHOLD:
                deleted_flow.append(flow)
                # del self.counter[flow]
            else:
                if value['count'] >= MAX_ATTACK:
                    self.logger.info('Block ' + flow)
                    self._ws_manager.broadcast(json.dumps({'type': 'block', 'data': flow}))
                    s_ip, d_ip, _ = flow.split('-')
                    for dpid, datapath in self.datapath_list.items():
                        self.logger.info(dpid)
                        parser = datapath.ofproto_parser
                        self.add_flow(datapath, 100, parser.OFPMatch(eth_type=0x0800, ipv4_src=s_ip, ipv4_dst=d_ip), [])
                        self.add_flow(datapath, 100, parser.OFPMatch(eth_type=0x0800, ipv4_src=d_ip, ipv4_dst=s_ip), [])
                    deleted_flow.append(flow)
        
        for f in  deleted_flow:
            del self.counter[f]

    
    def drop_flow(self, datapath, ip_src, ip_dst):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch(ipv4_src=ip_src, 
                                ipv4_dst=ip_dst) 

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, [])]
        mod = parser.OFPFlowMod(datapath=datapath,
                            command=ofproto.OFPFC_DELETE,
                            out_port=ofproto.OFPP_ANY,
                            out_group=ofproto.OFPG_ANY,
                            match=match, instructions=inst)  

        datapath.send_msg(mod)

    @set_ev_cls(idslib.EventAlert, MAIN_DISPATCHER)
    def _dump_alert(self, ev):
        msg = ev.msg

        # self.logger.info('alertmsg: %s' % ''.join(msg))
        self.process_msg(msg)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath



        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            # ignore lldp packet
            return
        dst = eth.dst
        src = eth.src

        # self.add_flow(datapath, 100, parser.OFPMatch(ipv4_src='10.0.0.1', ipv4_dst='10.0.0.2'), [])

        dpid = format(datapath.id, "d").zfill(16)
        self.mac_to_port.setdefault(dpid, {})

        if dpid not in self.datapath_list:
            self.datapath_list[dpid] = datapath
        # self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)

        # learn a mac address to avoid FLOOD next time.
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            # verify if we have a valid buffer_id, if yes avoid to send both
            # flow_mod & packet_out
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
