# DNSMuggle — pointing dnstunnel.cc.cd at your server

Right now the domain is registered but has 0 DNS records and shows
DNS Status: Unresolved. It does nothing until you point it at a
server you own.

## What you need first

A server with a public IP that runs the decoder on UDP port 53.
A Mininet VM behind NAT cannot do this. A small VPS is the usual
option, because many home ISPs block inbound port 53.

> Tested 2026-11-11: port forwarding to a home laptop is ruled out
> on this JioFiber connection — the router WAN IP is `<ROUTER_WAN_IP>`
> (CGNAT) while the public IP is `<PUBLIC_IP>`, so the internet
> cannot reach the router directly. A VPS with its own real public
> IP is the only internet route here. The same-Wi-Fi two-laptop
> test needs no VPS and no domain — see `TWO_LAPTOP_SETUP.md`.

## Records to add

In the domain panel:

1. Add an A record for the nameserver host, the glue record:
   `ns1.dnstunnel.cc.cd` -> your server's public IP
2. Set the domain's nameservers to your own server:
   `ns1.dnstunnel.cc.cd`

## Test it

DNS changes take minutes to a few hours to spread. Then:

```bash
dig NS dnstunnel.cc.cd
nslookup dnstunnel.cc.cd
```

Both should show your server as the nameserver.

## Run the decoder on the server

```bash
sudo python3 decoder.py --host 0.0.0.0 --port 53
```

Port 53 needs sudo. Then run the encoder from your own machine
with its defaults, which point at `dnstunnel.cc.cd` via the public
resolver `8.8.8.8`:

```bash
python3 encoder.py myfile.txt
```

## Notes

- Only test with your own files, from your own machine, to your
  own server.
- The domain expires 2027-11-11.
- If your provider does not allow custom nameservers on this
  subdomain, the real-domain step cannot be done there. The local
  loopback and Mininet demos still work without it.
