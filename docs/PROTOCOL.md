# DNSMuggle wire protocol

## Stream

```
<header JSON>\n<file bytes>
```

Header:

```json
{"filename": "secret.txt", "size": 10, "sha256": "<64 hex chars>",
 "compressed": false, "encrypted": false, "chunks": 10, "session": "482534"}
```

`size` and `sha256` describe the **original** file, before compression and
encryption, so size/SHA256 are verified against the plaintext end to end.
`compressed` and `encrypted` say which optional layers were applied.

`chunks` lives inside the header, and the header's own length decides the
chunk count, so the count is settled by iterating until it stops changing
(at most a couple of rounds; the encoded stream only ever grows).

## Layers, applied inside the stream

Before Base32, and in this order:

1. **compress** — zlib level 6, only when the file is larger than 1 KB.
   A small file skips it, and the header says so.
2. **encrypt** — only when a password is set. Fernet (AES-128-CBC +
   HMAC-SHA256) with a key from PBKDF2-HMAC-SHA256 (200 000 iterations,
   random 16-byte salt sent with the ciphertext). Without the
   `cryptography` package the app falls back to a SHA256 keystream XOR
   plus HMAC-SHA256 tag and records that in the blob's magic prefix.

The receiver reverses it: decrypt, then decompress, then verify `size` and
`sha256` against the header.

## Encoding

The stream is Base32-encoded, lowercased, with `=` padding stripped.
Base32 is used because DNS names allow only letters, digits and
hyphens and may be lowercased in transit. Base64's `+ / =` are not
DNS-safe. Cost: 5 bytes become 8 characters, about 60 percent overhead.

The sender splits the encoded string into labels of 16–63 Base32
characters (32 by default), numbered `001, 002, ...`. A 16-character
label carries 10 bytes; 32 carries 20; 63 carries up to 39 full bytes.
Each query supplies its own label boundary, so the receiver joins the
labels in sequence order without a chunk-size field in the header.
Labels longer than 40 characters trigger the detector's length rule.

## Queries

One DNS query per chunk, QTYPE A, QCLASS IN. The data is in the
question, the answer does not matter:

```
001.<chunk>.<session>.dnstunnel.cc.cd
002.<chunk>.<session>.dnstunnel.cc.cd
END.<session>.dnstunnel.cc.cd
```

`<session>` is a random 6-digit id generated per run, so a re-run does
not mix with a partial earlier session.

DNS packets are built by hand with the standard library only
(`socket` + `struct`): a 12-byte header plus a question section of
length-prefixed labels, a zero terminator, QTYPE and QCLASS. A
response echoes the question and adds one A answer (1.1.1.1).
The receiver sends an individual response with the same query ID for every
chunk, including duplicates. Packet format is unchanged.

## Windowed acknowledgements

The sender transmits up to 10 chunks with the configured delay between
them (default 0.01 seconds) before collecting their individual ACKs.
Responses may arrive out of order. A missing ACK times out after 2 seconds
per attempt; only that chunk is retransmitted, up to three attempts total.
The next window starts only when the current window is acknowledged; END
is sent only after all chunks are acknowledged. The final window may contain
fewer than 10 chunks.

## Decoding

The decoder stores chunks by sequence number. A retransmitted chunk
is ignored if its sequence number is already present. On END it sorts the chunks **numerically**
(string sorting would put `1000` before `999`), joins and decodes them,
splits off the header, writes the file, and checks size and SHA256
against the header. The CLI writes `recovered_<filename>` in the
current folder; the GUI writes to its `received/` folder and adds
`(1)`, `(2)` rather than overwriting.

## Worked example

`secret.txt` containing `Meet at 5\n` (10 bytes) becomes, after the
header and Base32, a stream of a few hundred characters. The GUI calculates
the exact count from the stream and selected chunk size; elapsed time also
depends on ACK latency, retransmissions, and the configured delay.

## Limits

- DNS traffic is not encrypted or authenticated by this protocol. Optional
  password encryption protects the file payload, not the query metadata.
- UDP only. Loss is handled per chunk, but a decoder restart loses
  the in-memory session. No resume.
- A query name must stay under 253 characters in total, and each
  label at most 63 characters. Custom domains still need to leave room
  for the sequence, chunk and session labels.
