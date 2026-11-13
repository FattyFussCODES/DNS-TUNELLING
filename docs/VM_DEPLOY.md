# DNSmuggle — permanent decoder on a free cloud VM

Plain idea first: a small free VM has its own real public IP,
so the internet can reach it. The decoder runs on it all the
time as a service, and your domain points at it. Your laptop
only sends — it never has to receive from the internet.

This is the permanent setup you asked for on 2026-11-11,
sized for 1 year: your subdomain `dnstunnel.cc.cd` is valid
until 2027-11-11, and the free VM below stays free as long as
you stay inside the Always Free limits.

## The card question — read first

Oracle **and** Google Cloud both need a card for verification,
even for the free tier. It is a temporary hold only (about
$1 on Oracle, $0–$1 on Google), refunded, not a charge for
the VM. Do not try a fake or virtual card — it will be
rejected.

- **Have a card:** your own Visa/Mastercard debit card with
  international / online transactions enabled in your bank
  app, or a parent's card **with their permission**, for
  verification only.
- **No card at all:** you cannot create an Oracle, Google,
  AWS or Azure free VM. Use `PLAYIT_TEST.md` tonight
  (no card, internet test to your laptop) and the local
  two-laptop test in `TWO_LAPTOP_SETUP.md`. Do not use
  obscure "free VPS, no card" sites found by search — the
  ones checked on 2026-11-11 were short trials (72 hours /
  30 days), waitlisted, or unverified, and none of them
  meets a 1-year permanent bar.

Pick one provider. **Oracle first, Google second** — Oracle's
Always Free VM is bigger and never expires; Google's e2-micro
is smaller but easier to set up.

## Step 1: create the VM

### Oracle Cloud Always Free (first choice)

1. Go to https://cloud.oracle.com and log in.
2. Compute → Instances → Create Instance.
3. Name: `dns-decoder`.
4. Image: **Ubuntu 22.04**. Not Windows — the decoder is a
   Python script made for Linux.
5. Shape — pick an Always Free one:
   - **VM.Standard.A1.Flex**, 1 OCPU, 6 GB RAM (ARM), or
   - **VM.Standard.E2.1.Micro**, 1 OCPU, 1 GB RAM (AMD)
   Either is enough for the decoder.
6. Networking: keep the default VCN, make sure **Assign a
   public IPv4 address** is checked.
7. Add SSH key: paste your public key, or let Oracle
   generate a key pair and download the private key. Save
   that file — you need it to log in.
8. Create. Wait for Running, note the **Public IP**.
   This is your `<VM-IP>`. Keep it — the domain step
   points at it.

### Google Cloud Free Tier (second choice)

1. Go to https://cloud.google.com and sign up (card for
   verification only, as above).
2. Create a VM: **e2-micro, 1 vCPU, 1 GB RAM, 30 GB disk,
   Ubuntu 22.04**, in a free region — `us-east1`,
   `us-west1` or `us-central1` only. The same VM in Mumbai
   or Singapore is **not** free.
3. Reserve a **static external IP** (VPC Network → IP
   Addresses → Reserve) and attach it to the VM. Do not
   use the temporary IP — it can change on restart.
   Note it as your `<VM-IP>`.

## Step 2: open the firewall — both layers

### Oracle: cloud security list + inside the VM

1. Networking → Virtual Cloud Networks → your VCN →
   Security Lists → Default Security List → Add Ingress:
   - Source `0.0.0.0/0`, protocol **UDP**, port **53**
   - Source `0.0.0.0/0` (or your IP only, stricter),
     protocol **TCP**, port **22** for SSH
2. After SSH (Step 3), inside the VM:
   ```bash
   sudo iptables -I INPUT -p udp --dport 53 -j ACCEPT
   sudo apt-get install -y iptables-persistent
   sudo netfilter-persistent save
   ```
   If the save step is skipped, the iptables rule works
   until a reboot only.

### Google: cloud firewall only

1. VPC Network → Firewall → Create a rule allowing
   ingress **UDP 53** from `0.0.0.0/0`.
2. Allow **TCP 22** for SSH (from your IP only if you
   can).
3. Google VMs do not need a second iptables step for
   this — the cloud firewall is the gate.

## Step 3: copy the decoder to the VM

From your laptop, in the `DNSMuggle` folder:

```bash
# Oracle (user is ubuntu; replace <key.pem> and <VM-IP>)
scp -i <key.pem> decoder.py ubuntu@<VM-IP>:~/

# Google (use the username shown in the console)
scp decoder.py <username>@<VM-IP>:~/
```

Then SSH in:

```bash
ssh -i <key.pem> ubuntu@<VM-IP>
# or: ssh <username>@<VM-IP>
```

On the VM, put it in its own folder and test it once:

```bash
mkdir -p ~/dns-tunnel
mv ~/decoder.py ~/dns-tunnel/
cd ~/dns-tunnel
sudo python3 decoder.py --host 0.0.0.0 --port 53
```

Leave that running for the first test, then stop it with
Ctrl+C and make it a service (Step 4). Port 53 needs sudo.

## Step 4: make the decoder run forever (systemd)

On the VM, create `/etc/systemd/system/dns-decoder.service`:

```ini
[Unit]
Description=DNSmuggle decoder
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/ubuntu/dns-tunnel/decoder.py --host 0.0.0.0 --port 53
WorkingDirectory=/home/ubuntu/dns-tunnel
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

Notes:
- If your VM username is not `ubuntu` (Google), change
  both `/home/ubuntu/` paths to your home folder.
- Check the Python path first: `which python3` — if it is
  not `/usr/bin/python3`, use the path it prints.
- `WorkingDirectory` matters: the decoder writes
  `recovered_<filename>` in that folder.
- `User=root` is because port 53 needs root. The decoder
  only listens and writes files in its own folder.

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable dns-decoder
sudo systemctl start dns-decoder
sudo systemctl status dns-decoder
```

Check it is alive and see its logs:

```bash
sudo systemctl is-active dns-decoder
sudo journalctl -u dns-decoder -f
```

Now the decoder starts on boot and restarts if it crashes.
No terminal needs to stay open.

## Step 5: test directly to the VM IP (before the domain)

From your laptop, anywhere (not just home Wi-Fi):

```bash
python3 encoder.py examples/secret.txt --server <VM-IP> --port 53 --delay 0.05
```

On the VM, check the rebuilt file:

```bash
cd ~/dns-tunnel
ls -l recovered_*
diff examples/secret.txt recovered_secret.txt
```

You need `examples/secret.txt` on the VM for that `diff`,
or just read the decoder log: it prints
`size match: True` and `sha256 match: True` on a pass.
Copy the example file over if you want the diff check:

```bash
scp -i <key.pem> examples/secret.txt ubuntu@<VM-IP>:~/dns-tunnel/
```

Only do the domain step after this direct test passes.

## Step 6: point your domain at the VM (once)

In your domain panel for `dnstunnel.cc.cd`:

1. Add an A record (glue record):
   `ns1.dnstunnel.cc.cd` → `<VM-IP>`
2. Set the nameservers for `dnstunnel.cc.cd` to:
   `ns1.dnstunnel.cc.cd`
3. Wait for propagation — minutes to a few hours, then:
   ```bash
   dig NS dnstunnel.cc.cd
   nslookup dnstunnel.cc.cd
   ```
   Both should show your VM as the nameserver.

Then the full public route, from your laptop:

```bash
python3 encoder.py examples/secret.txt
```

No `--server` needed — the encoder defaults to
`8.8.8.8:53`, the public resolver looks up your domain,
and forwards the questions to your VM. Pass is the same:
size and sha256 match True on the VM.

Full detail is also in `DOMAIN_SETUP.md`.

## What is permanent, and what is not

Permanent (set once, leave alone):
- The VM and its static public IP, inside the Always Free
  limits.
- The decoder as a systemd service, always on.
- The domain setup, once NS + glue are set.

Not permanent yet:
- `dnstunnel.cc.cd` expires **2027-11-11**. Renew it
  before then, or buy your own domain (~₹800/year) and
  point that one at the same VM instead. The VM does not
  need to change.

## Cost guardrails — stay free

- Oracle: stay on the Always Free shape above. Do not
  create a second VM, a bigger shape, or a paid service.
- Google: stay on e2-micro in `us-east1` / `us-west1` /
  `us-central1`, 30 GB disk, 1 GB egress/month. Do not
  spend the $300 trial credit on a bigger machine.
- Never click Upgrade on either account. If a bill or
  a charge warning appears, stop the VM and check what
  resource caused it before doing anything else.
- Your DNS test files are tiny — a few KB per run — so
  bandwidth is not a risk here.
