# DNSmuggle — internet test with Playit.gg, no card, no VPS

Plain idea first: Playit.gg is a free tunnel, not a DNS server.
You run its agent on Laptop A. The agent connects *out* to
Playit, so your Jio CGNAT does not block it. Playit gives you
a public address, and forwards packets sent to that address
back to the decoder on Laptop A.

This is the no-card internet test. It works tonight, from a
different network. It is **not** the permanent setup, and it
cannot be your domain's DNS server — see Limits below.

## What you need

- Laptop A (decoder) and Laptop B (encoder), with the
  `DNSMuggle` folder on both.
- A free Playit.gg account — email only, no card.
- Laptop B on a *different* network from home Wi-Fi for the
  real test (phone hotspot is fine).

## Step 1: prove it locally first

Do the two-laptop test in `TWO_LAPTOP_SETUP.md` first, on
port 5353. If that does not pass, Playit will not fix it —
the tunnel only moves packets, it does not fix the code.

## Step 2: start the decoder on Laptop A

On Laptop A, in the `DNSMuggle` folder:

```powershell
python3 decoder.py --host 127.0.0.1 --port 5353
```

Leave it running. Port 5353 needs no admin rights.
Use 127.0.0.1 here, because the Playit agent forwards to
that address on this same laptop.

If Windows Firewall asks, allow Python through on private
networks (UDP 5353).

## Step 3: install the Playit agent on Laptop A

1. Go to https://playit.gg and create a free account.
2. Download the agent for Windows from playit.gg/download
   and run it on Laptop A.
3. The agent shows a claim code / link. Open it and add the
   agent to your account. Only accept a code your own agent
   printed.

Free plan (checked 2026-11-11): 4 ports, 2 agents, no card.

## Step 4: create a UDP tunnel

In the Playit dashboard, Tunnels → Add Tunnel:

- Tunnel type: **UDP** (plain UDP — not a game preset)
- Local IP: `127.0.0.1`
- Local port: `5353`
- Region: Global Anycast (free)

Playit assigns a public address, something like:

```
something.ply.gg:41234
```

Note down **both** parts exactly as shown: the hostname/IP
and the port. The port is a random high port, not 53 — that
is normal, and it is why this cannot be a DNS server (below).

## Step 5: send from Laptop B, from another network

Put Laptop B on your phone's hotspot (not home Wi-Fi), then
in the `DNSMuggle` folder on Laptop B:

```powershell
python3 encoder.py examples/secret.txt --server <playit-address> --port <playit-port> --delay 0.05
```

Replace `<playit-address>` and `<playit-port>` with the two
parts Playit gave you. Do **not** use `8.8.8.8` here, and do
not use port 53 — send to Playit's address and port.

Example (your numbers will differ):

```powershell
python3 encoder.py examples/secret.txt --server something.ply.gg --port 41234 --delay 0.05
```

## Step 6: check the result on Laptop A

The decoder should print chunk lines, then:

```
size match: True
sha256 match: True
```

Then on Laptop A:

```powershell
fc examples\secret.txt recovered_secret.txt
```

No differences = pass. If a chunk fails after 3 retries,
re-run the encoder — each run gets a new session id.

## If it does not work

1. Decoder not running on Laptop A, or started after the
   encoder. Start the decoder first, then re-run.
2. Tunnel points at the wrong local port. It must be
   `127.0.0.1:5353`, matching the decoder command above.
3. Playit agent offline on Laptop A. The tunnel dies if the
   agent stops or the laptop sleeps — keep Laptop A awake
   and the agent running for the whole test.
4. Wrong public address/port copied from Playit. Copy both
   parts again from the dashboard; do not guess the port.
5. Windows Firewall on Laptop A blocking UDP 5353.

## Limits — read before calling this permanent

- **No port 53.** Playit gives a random high port. Public
  DNS only works on port 53, so a resolver like `8.8.8.8`
  will never send questions to a Playit address.
- **No domain support.** You cannot set
  `dnstunnel.cc.cd`'s nameserver to a Playit address: an NS
  record only points to an IP, it cannot point to a port.
  The full public-DNS route through your domain still
  needs a VPS with a real public IP on port 53 — see
  `VM_DEPLOY.md`.
- **Not a real DNS server.** Playit only forwards packets.
  It does not answer DNS or do NS lookups.
- **Agent must stay running.** If the agent stops, or
  Laptop A sleeps or disconnects, the tunnel is down.
- **Address can change.** If you delete and recreate the
  tunnel, Playit may give a different address/port.
- **Playit sees your traffic.** The tunnel is not
  end-to-end encrypted by Playit; your DNS questions pass
  through their servers in plain text, same as plain DNS.
- **Free routing can be slower.** Free tunnels use global
  anycast routing, which can add latency. Your test files
  are tiny, so this should not matter here.

## When to use which route

- No card tonight, want an internet test: **this file**.
- Have a card (your Visa/Mastercard debit with
  international transactions on, or a parent's card with
  their permission): **VM_DEPLOY.md** — the permanent
  1-year setup, decoder always on, domain pointed at it.
- No card at all, ever: local tests only (loopback and
  two-laptop), plus this Playit test. The code still
  proves the tunnel works.
