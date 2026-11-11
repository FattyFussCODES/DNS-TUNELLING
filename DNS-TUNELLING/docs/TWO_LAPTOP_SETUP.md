# Two-laptop test, no Mininet needed

You have two laptops. That is the cleanest test: one is the sender,
one is the receiver, on a real network, with no virtual machines.

## The setup

```
Laptop B (encoder, sender)  ── Wi-Fi ──>  Laptop A (decoder, receiver)
   your test file                          rebuilds recovered_<file>
```

- Laptop A runs `decoder.py`. It is the server.
- Laptop B runs `encoder.py`. It is the sender.
- Both laptops must be on the same Wi-Fi network.
- Test only with your own files, from your own laptops, to your
  own server. Never run this against someone else's machine.

## Step 1: Laptop A, find its Wi-Fi IP

Linux:

```bash
ip addr
```

Windows:

```bash
ipconfig
```

Look for the Wi-Fi address, something like `192.168.1.5`.
That is the address Laptop B will send to. It changes if the
laptop reconnects, so check it each time.

## Step 2: Laptop A, allow the port and start the decoder

The decoder listens on UDP port 53, which needs sudo on Linux.
If your firewall blocks it, allow UDP 53 for Python, or use
port 5353 on both sides instead, which needs no sudo.

```bash
# Option 1: real DNS port
sudo python3 decoder.py --host 0.0.0.0 --port 53

# Option 2: no sudo, test port
python3 decoder.py --host 0.0.0.0 --port 5353
```

Leave it running. It prints each chunk as it arrives.

## Step 3: Laptop B, send a test file

Copy `encoder.py` and a test file to Laptop B first. Then:

```bash
# If Laptop A is on port 53, IP 192.168.1.5
python3 encoder.py examples/secret.txt --server 192.168.1.5 --port 53 --delay 0.05

# If Laptop A is on port 5353 instead
python3 encoder.py examples/secret.txt --server 192.168.1.5 --port 5353 --delay 0.05
```

Do not use `8.8.8.8` here. That is only for the real-domain
test, where the public resolver forwards to your nameserver.
On your own Wi-Fi, send directly to Laptop A's IP.

## Step 4: check the result on Laptop A

The decoder should print:

```
size match: True
sha256 match: True
```

Then on Laptop A:

```bash
diff examples/secret.txt recovered_secret.txt
```

It should print nothing, which means the rebuilt file is
identical to the original.

## If it does not work

1. **No chunks arrive:** check both laptops are on the same
   Wi-Fi, check Laptop A's IP again, and check Laptop A's
   firewall is allowing UDP on the port you chose.
2. **Permission denied on port 53:** use port 5353 on both
   sides, or run the decoder with sudo.
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
run. The real-domain test in `DOMAIN_SETUP.md` is the same
code, just with the public resolver and your nameserver in
the middle instead of a direct Wi-Fi address.
