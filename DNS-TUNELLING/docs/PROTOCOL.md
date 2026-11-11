# Protocol

## Stream

```
<header JSON>\n<file bytes>
```

Header:

```json
{"filename": "secret.txt", "size": 10, "sha256": "<64 hex chars>"}
```

Chunk count is deliberately not in the header, because it would depend
on the header's own length. Completion is signalled by the END query
instead.

## Encoding

The stream is Base32-encoded, lowercased, with `=` padding stripped.
Base32 is used because DNS names allow only letters, digits and
hyphens and may be lowercased in transit. Base64's `+ / =` are not
DNS-safe. Cost: 5 bytes become 8 characters, about 60 percent overhead.

The encoded string is split into 32-character chunks, well under the
63-character per-label DNS limit, numbered `001, 002, ...`.

## Queries

One DNS query per chunk, QTYPE A, QCLASS IN. The data is in the
question, the answer does not matter:

```
001.<32-char chunk>.<session>.dnstunnel.cc.cd
002.<32-char chunk>.<session>.dnstunnel.cc.cd
END.<session>.dnstunnel.cc.cd
```

`<session>` is a random 6-digit id generated per run, so a re-run does
not mix with a partial earlier session.

DNS packets are built by hand with the standard library only
(`socket` + `struct`): a 12-byte header plus a question section of
length-prefixed labels, a zero terminator, QTYPE and QCLASS. A
response echoes the question and adds one A answer (127.0.0.1). The
encoder treats any response with a matching query ID as the ACK for
that chunk and resends on timeout, up to 3 tries.

## Decoding

The decoder stores chunks by sequence number. A retransmitted chunk
just overwrites the same slot. On END it sorts the chunks, joins and
decodes them, splits off the header, writes `recovered_<filename>`,
and checks size and SHA256 against the header.

## Worked example

`secret.txt` containing `Meet at 5\n` (10 bytes) becomes, after the
header and Base32, a stream of a few hundred characters, so a handful
of queries. A 1 KB file is about 1,640 Base32 characters, about
52 queries at the default 0.2 second delay, about 10 seconds.

## Limits

- Plain DNS only, no encryption or authentication.
- UDP only. Loss is handled per chunk, but a decoder restart loses
  the in-memory session. No resume.
- A query name must stay under 253 characters in total, and each
  label under 63 characters. The 32-character chunk size keeps both
  comfortably in range.
