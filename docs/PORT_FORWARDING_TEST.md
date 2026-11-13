# DNSMuggle — test port forwarding before touching nameservers

> **VERDICT for this connection — tested 2026-11-11, do not re-try:**
> Your JioFiber router's WAN IP is `<ROUTER_WAN_IP>` (a private `10.`
> address) while "what is my ip" shows `<PUBLIC_IP>`. They do not
> match, so you are behind **CGNAT**. Port forwarding from the
> internet to your laptop **cannot work on this connection**,
> whatever you set on the router. The internet route for this
> project is a VPS instead — see `DOMAIN_SETUP.md`. The two-laptop
> test on the same Wi-Fi (`docs/TWO_LAPTOP_SETUP.md`) is unaffected
> and is the next step. The rest of this file is kept as the record
> of how the check was done.

You asked: can I forward port 53 on my router to my laptop
instead of renting a VPS? Yes. This file is the test for that
route, written so you find out in minutes whether it works,
instead of setting up nameservers, waiting hours for DNS to
spread, and only then discovering your ISP blocks port 53.

Plain idea first: your laptop becomes the server. Your router
has the public IP that the internet can see. Port forwarding
tells the router: "any DNS question that arrives from the
internet on UDP port 53, send it to my laptop." The decoder
on the laptop then answers it, same as before.

## The shortcut: test with your public IP, not the domain

Do NOT do the nameserver / glue-record steps first. Point the
encoder straight at your public IP. If that works, port
forwarding works, and only then is it worth doing the domain
steps. If it fails, the domain steps would have failed too,
and you have saved the waiting time.

```bash
# Laptop B (the sender), from a DIFFERENT network than home Wi-Fi
python3 encoder.py examples/secret.txt --server <your-public-IP> --port 53 --delay 0.05
```

The encoder sends raw DNS packets to whatever `--server` you
give it. It does not need the domain to resolve for this test.
The domain name `dnstunnel.cc.cd` is only written inside each
packet so the decoder knows the packet is for it.

## Step 0: check for CGNAT first (2 minutes, decides everything)

If your ISP uses CGNAT, port forwarding cannot work, no matter
what you set on the router. Check before you change anything:

1. Log in to your router (usually `<ROUTER_LAN_IP>` or
   `<ROUTER_LAN_IP>` in a browser) and find the WAN / Internet IP
   it shows.
2. On any device, search "what is my ip" and note that address.
3. Compare them:
   - **They match, and the WAN IP is NOT in `100.64.x.x` to
     `100.127.x.x`** — you have a real public IP. Port
     forwarding can work. Continue below.
   - **They do not match, or the WAN IP is in `100.64.x.x` to
     `100.127.x.x`** — you are behind CGNAT. Your public IP
     is shared with other houses, so the router cannot receive
     traffic for you alone. Stop here: use a VPS instead
     (see `DOMAIN_SETUP.md`). No router setting fixes this.

## Step 1: give your laptop a fixed Wi-Fi IP

Your laptop's Wi-Fi IP (something like `<PEER_LAN_IP>`) can
change every time it reconnects, and then the forwarding rule
points at the wrong machine. In the router settings, set a
DHCP reservation for your laptop so it always gets the same
IP. Note that IP down.

## Step 2: add the port-forwarding rule on the router

In the router, find Port Forwarding (sometimes called Virtual
Server). Add one rule:

- Service / port: `53`
- Protocol: `UDP` (not TCP, not both — UDP only)
- Internal IP: your laptop's fixed Wi-Fi IP from Step 1
- Internal port: `53`

Save it.

## Step 3: allow UDP 53 through the laptop firewall

- Windows: allow incoming UDP port 53 through Windows
  Firewall for Python (or for the decoder). Run the terminal
  as Administrator when you start the decoder.
- Linux: allow UDP 53 with your firewall tool, or test with
  the firewall off on your own home Wi-Fi and turn it back
  on after.

## Step 4: start the decoder on the laptop (Laptop A)

In the `DNSMuggle` folder on Laptop A, leave this running:

```bash
sudo python3 decoder.py --host 0.0.0.0 --port 53
```

On Windows, run the terminal as Administrator instead of
`sudo`. Keep the laptop on and on Wi-Fi the whole test. If
it sleeps or disconnects, the server is down.

## Step 5: send from OUTSIDE your home Wi-Fi

This is the part people get wrong. If Laptop B is on the
same Wi-Fi and sends to your public IP, some routers answer
it themselves and the test proves nothing. Send from a
different network instead:

- Put Laptop B on your phone's mobile hotspot, or
- Use mobile data / a different Wi-Fi network.

Then, on Laptop B:

```bash
python3 encoder.py examples/secret.txt --server <your-public-IP> --port 53 --delay 0.05
```

Replace `<your-public-IP>` with the "what is my ip" address
from Step 0.

## How to read the result

**It works** — the decoder on Laptop A prints the chunks
arriving, then `size match: True` and `sha256 match: True`,
and `diff examples/secret.txt recovered_secret.txt` on
Laptop A prints nothing. Port forwarding works. Now do the
domain steps in `DOMAIN_SETUP.md` (glue record, then
nameservers), and afterwards the encoder works with its
defaults (`python3 encoder.py examples/secret.txt`, via
`8.8.8.8`).

**It fails** — the encoder stops on chunk 1, "failed after
3 retries", and nothing arrives on Laptop A. Work through
this order, cheapest first:

1. Decoder not running on Laptop A, or started after the
   encoder. Start the decoder first, then re-run the encoder.
2. Wrong public IP (it changes when the router restarts —
   check "what is my ip" again), or the laptop's Wi-Fi IP
   changed (Step 1 not done).
3. Firewall on Laptop A blocking UDP 53.
4. Router rule wrong: protocol set to TCP, or pointed at
   the wrong internal IP or port.
5. Your ISP blocks incoming port 53, or you are behind
   CGNAT after all. If 1–4 are all correct and it still
   fails, this is the most likely reason, and a VPS is the
   reliable route — a VPS has a real public IP with port
   53 open.

One more check before blaming the ISP: some mobile networks
block outgoing UDP 53 to anything except their own resolver.
If the hotspot test fails, try once more from a different
outside network (another Wi-Fi) before concluding it is
blocked on your home side.

## After the test

- If it worked, your public IP can still change every few
  days or when the router restarts. Each time it changes,
  the glue record (`ns1.dnstunnel.cc.cd` -> your IP) points
  at the old address until you update it.
- Close the forwarding rule when you are done testing. You
  opened a port on your laptop to the whole internet; only
  keep it open while the decoder is running for your own
  test, with your own files, to your own laptop.
- The domain expires 2027-11-11.
