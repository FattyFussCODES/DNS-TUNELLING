# Demo script — DNS tunnelling over Skein

Lab-only demo, on your own laptops, with your own test files.
Written 2026-11-12 from the 2026-11-11 run, when the decoder was
already listening on the Skein address.

## What the audience sees

1. Two laptops behind CGNAT join one private mesh and get overlay
   addresses (e.g. `<SKEIN_DECODER_IP>`, `<SKEIN_SENDER_IP>`).
2. A file is smuggled from one laptop to the other hidden inside
   DNS questions, and rebuilt byte-identical on the other side.

## Before the demo — the one thing still unproven

On 2026-11-11 at 18:32 UTC the decoder was running on Laptop A:

```
Decoder listening on <SKEIN_DECODER_IP>:53 for *.dnstunnel.cc.cd
Waiting for chunks... (Ctrl+C to stop)
```

The encoder run from Laptop B had not been reported yet. Run the
check in "Step 2" below once, before you demo in front of anyone.
Pass = decoder prints `size match: True` and `sha256 match: True`,
and `fc` on Laptop A shows no differences.

## Step 0: both laptops in the mesh

On 2026-11-11 Laptop A showed `Peers 0/0`, `Capacity 1 of 5` —
only Laptop A was in the mesh, even though both laptops were on
the same Wi-Fi. Laptop B must join before anything else works.

On Laptop A: Skein Desktop → **Invitations** → **Create invitation**
→ copy the join string (`skein:1:...`).

On Laptop B: Skein Desktop → **Join a network** → paste the string
→ approve the admin prompt.

Check on Laptop A: it should now read **Peers 1/1**,
**Capacity 2 of 5**, with a second node on the map at its own
`<SKEIN_IP>` address (probably `<SKEIN_SENDER_IP>`).

Test the mesh from Laptop B:

```powershell
ping <SKEIN_DECODER_IP>
```

If that replies, the mesh works. If Peers is still 0/0, stop here —
the DNS test cannot work until Laptop B has joined.

## Step 1: Laptop A — start the decoder

In PowerShell **as Administrator** (port 53 needs admin rights),
in the `DNS-TUNELLING` folder:

```powershell
python decoder.py --host <SKEIN_DECODER_IP> --port 53
```

Windows notes, from the 2026-11-11 run:

- Use `python`, not `python3` — on Windows `python3` is not
  recognised.
- `cd` into the `DNS-TUNELLING` folder first; running from
  `C:\Users\bohra>` fails because `decoder.py` is not there.
- If port 53 is a problem, use port 5353 instead (no admin needed)
  and match it on the encoder side with `--port 5353`.

Leave this window open. Do not press Ctrl+C until the transfer
is done.

## Step 2: Laptop B — send the file

On Laptop B, in the same `DNS-TUNELLING` folder:

```powershell
python encoder.py examples/secret.txt --server <SKEIN_DECODER_IP> --port 53 --delay 0.05
```

What you should see:

- Laptop B: the file, number of chunks, then
  `Done: X/X chunks sent, END sent`.
- Laptop A: chunk lines arriving one by one, then
  `size match: True` and `sha256 match: True`.

Then, on Laptop A, check the rebuilt file:

```powershell
fc examples\secret.txt recovered_secret.txt
```

No differences = pass. That is the whole proof for the demo.

## Step 3: say the two layers out loud

- **Skein is the road.** An encrypted mesh VPN that lets the two
  laptops reach each other even behind CGNAT. It gives them
  private overlay IPs and forwards the traffic.
- **DNS tunnelling is the vehicle.** The file is cut into Base32
  chunks, hidden inside DNS questions, sent over UDP with ACKs
  and an END marker, and rebuilt by the decoder.

## Be honest about the limit (say this in the demo)

Running the tunnel inside Skein does **not** prove it works over
public DNS. The questions travel inside Skein's encrypted tunnel,
so a public resolver never sees them. Say it plainly: "Skein gives
me the transport, the DNS protocol on top is the same, but the
public DNS route would need a decoder reachable on port 53" — that
is the VM route in `docs/VM_DEPLOY.md`, or the IPv6 route in
`docs/DOMAIN_SETUP.md`, both still untested.

Other limits worth one line each: Skein is early software
(`0.1.0-dev`, 2–5 nodes); on Windows it needs the Wintun driver;
if the mesh goes down, the laptops lose each other.

## If it fails on the day

- `Peers 0/0` on Laptop A → Laptop B has not joined; redo Step 0.
- `python3` not recognised → use `python`.
- Decoder says nothing when the encoder runs → check both laptops
  are in Skein (`ping <SKEIN_DECODER_IP>` from Laptop B) and that the
  `--port` matches on both sides (53 or 5353).
- Encoder stops naming a chunk after 3 tries → re-run it; each run
  gets a new session id, so a partial old session is abandoned,
  not mixed in.
- Fallback that needs no mesh at all: the same-Wi-Fi test in
  `docs/TWO_LAPTOP_SETUP.md` (decoder on `<DECODER_LAN_IP>`).
