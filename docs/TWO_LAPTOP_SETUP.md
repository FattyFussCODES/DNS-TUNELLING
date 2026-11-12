# Two-laptop test, no Mininet needed — your setup

You have two laptops. That is the cleanest test: one is the sender,
one is the receiver, on a real network, with no virtual machines.
No domain is needed for this test — the domain is only for the
internet test later, via a VPS (see below).

## Your numbers, verified 2026-11-11

- Router (JioFiber JC0500, Wi-Fi `JioFiber-kc1Vd`): `192.168.29.1`
- Laptop A, decoder (from your `ipconfig` screenshot): `192.168.29.184`
- Laptop A Wi-Fi MAC (for the DHCP reservation): `64:32:A8:E5:AC:36`
- Your network is `192.168.29.x` — not `192.168.1.x`. Ignore any
  `192.168.1.5` example; use `192.168.29.184` everywhere below.
- Your public IP (what the internet sees): `49.36.139.72`
- Your router's WAN IP: `10.12.3.110` — a private `10.` address.
  That means you are behind CGNAT, so port forwarding from the
  internet to your laptop **cannot work on this connection**
  (see `PORT_FORWARDING_TEST.md`). That does not affect this
  test at all: both laptops are inside your house, no internet
  needed.

## The setup

```
Laptop B (encoder, sender)  ── same Wi-Fi ──>  Laptop A (decoder, receiver)
   your test file                              rebuilds recovered_<file>
```

- Laptop A runs `decoder.py`. It is the server.
- Laptop B runs `encoder.py`. It is the sender.
- Both laptops must be on the same Wi-Fi network
  (`JioFiber-kc1Vd` or `JioFiber-kc1Vd_5G` — same network either way,
  as long as both are on it).
- Test only with your own files, from your own laptops, to your
  own server. Never run this against someone else's machine.

## Step 0 (once): give Laptop A a fixed Wi-Fi IP

`192.168.29.184` can change when Laptop A reconnects, and then
Laptop B would be sending to the wrong address. Fix it once in
the router, so Laptop A always gets `192.168.29.184`:

1. In a browser go to `http://192.168.29.1` and log in as `admin`
   (password is on the sticker on the bottom of the router).
2. Go to **NETWORK**, then **LAN**, then **DHCP** — that is where
   the fixed-IP page lives on this router.
3. Add a DHCP reservation: MAC `64:32:A8:E5:AC:36` →
   IP `192.168.29.184`. Save.
4. Disconnect and reconnect Laptop A's Wi-Fi, then run `ipconfig`
   and check it still shows `192.168.29.184`.

If you skip this step, re-check Laptop A's IP with `ipconfig`
every time before you run the test.

## Step 1: Laptop A, start the decoder

Start with port 5353 — no admin rights needed, and it proves the
code works before you fight Windows Firewall on port 53.

```powershell
cd DNS-TUNELLING
python3 decoder.py --host 0.0.0.0 --port 5353
```

Leave it running. It prints each chunk as it arrives.

Only switch to the real DNS port once 5353 works:

```powershell
# Run PowerShell as Administrator for this one
python3 decoder.py --host 0.0.0.0 --port 53
```

If Windows Firewall asks, allow Python through on private
networks. If nothing arrives on port 53, go back to 5353 —
the tunnel logic is identical, only the port differs.

## Step 2: Laptop B, send a test file

Copy the `DNS-TUNELLING` folder to Laptop B first (USB, or
`git clone https://github.com/FattyFussCODES/DNS-TUNELLING.git`).
Then, in that folder on Laptop B:

```powershell
# Match the port Laptop A is listening on — 5353 first
python3 encoder.py examples/secret.txt --server 192.168.29.184 --port 5353 --delay 0.05

# Once that works, the port-53 version is the same, with --port 53
python3 encoder.py examples/secret.txt --server 192.168.29.184 --port 53 --delay 0.05
```

Do not use `8.8.8.8` here. That is only for the real-domain
test, where the public resolver forwards to your nameserver.
On your own Wi-Fi, send directly to Laptop A's IP.
No domain lookup happens in this test — `dnstunnel.cc.cd` is
only written inside each packet as a label, so the decoder
knows the packet is for it.

## Step 3: check the result on Laptop A

The decoder should print:

```
size match: True
sha256 match: True
```

Then on Laptop A, check the rebuilt file is identical:

```powershell
fc examples\secret.txt recovered_secret.txt
```

It should report no differences. (On Linux the same check is
`diff examples/secret.txt recovered_secret.txt`, which prints
nothing on a match.)

## If it does not work

1. **No chunks arrive:** check both laptops are on the same
   Wi-Fi, check Laptop A's IP again with `ipconfig` (Step 0),
   and check Laptop A's firewall is allowing UDP on the port
   you chose.
2. **Permission denied on port 53:** use port 5353 on both
   sides, or run the decoder's PowerShell as Administrator.
3. **Encoder stops on a chunk:** the decoder is probably not
   running, or the IP is wrong. Start the decoder first, then
   re-run the encoder. A new session id is generated each run,
   so a partial old session is abandoned, not mixed in.
4. **Works on loopback but not between laptops:** that is
   almost always the firewall on Laptop A. Allow the port,
   or temporarily test with the firewall off on your own
   home Wi-Fi, and turn it back on after.

## After this works

Try a bigger file, then a small PNG, then a slower `--delay 1`
run. The internet test is the same code, just with a VPS in
the middle instead of a direct Wi-Fi address — because CGNAT
rules out port forwarding to your laptop, the VPS route in
`DOMAIN_SETUP.md` is the only internet route for this
connection. Do the domain/nameserver steps only after you
have a VPS with a real public IP.
