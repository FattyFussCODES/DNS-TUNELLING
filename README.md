<p align="center">
  <img src="https://raw.githubusercontent.com/FattyFussCODES/DNSmuggle/main/docs/screenshots/dnsmuggle-logo.png" alt="DNSmuggle" width="300">
</p>

# DNSmuggle

DNSMuggle 1.1.0 is a DNS transfer and detection lab for authorized
environments. The main desktop application combines Send, Receive, History,
Detector, and Settings in one window. A separate defensive workbench provides
additional DNS telemetry analysis.

> **Lab only. Test only with your own files, from your own machines, to
> a server you own.** Never point this at someone else's machine, a real
> network you do not control, a college or work network, or a public
> site without permission. The "victim" in every demo here is your own
> host: you create the test file and start the encoder yourself. There
> is no infiltration step in this project.

## Optional defensive workbench

Install the `workbench` extra (see below), then launch `dnsmuggle-workbench`
or `python -m app.workbench.desktop` to open the separate telemetry workbench.
Configure a numeric listen address and port, start monitoring, and inspect
observations, detector alerts, and summaries. The workbench stores observation
metadata and can generate text reports; PDF reports require the `pdf` extra.

The screenshots show the actual workbench with synthetic loopback queries:

![Workbench overview with synthetic observations](https://raw.githubusercontent.com/FattyFussCODES/DNSmuggle/main/docs/screenshots/workbench-overview.png)

![Traffic analysis with synthetic observations](https://raw.githubusercontent.com/FattyFussCODES/DNSmuggle/main/docs/screenshots/workbench-traffic.png)

The listener sees only DNS queries intentionally delivered to its configured
UDP endpoint. It does not capture network traffic, reply to or forward DNS
queries, or reconstruct files. Length, entropy, and rate rules are heuristics,
not proof of tunnelling. A per-rule, per-source cooldown can suppress alert
evidence, so the flag rate is not detection accuracy.

## Main application

Launch `dnsmuggle` or `python -m app.main` for the transfer and detection
window. Its pages are **Send**, **Receive**, **History**, **Detector**, and
**Settings**. `dnsmuggle-lab` and `python -m app.lab_main` open the same window.
The screenshots below show the redesigned main application.

### How to use the transfer lab

![Send page](https://raw.githubusercontent.com/FattyFussCODES/DNSmuggle/main/docs/screenshots/lab-send.png)

### 1. Start the receiver first

**Receive** tab → Host `127.0.0.1`, Port `5353` → **Start**. The status
line turns green and the chunk table starts empty. Leave this window running.
If port 5353 is occupied, choose another free UDP port.

### 2. Send a file

**Send** tab → **Choose file** → Preset `Loopback` → **Send**. If you chose
a different receiver port, enter it in the Send tab as well. For another
machine, select `Custom` and enter your decoder's address and port.
Select a Base32 chunk size from 16–63 characters (32 by default) and a delay
(0.01 seconds by default). The preview shows the actual chunk count and
estimated time; the log shows ACK counts for each window.

### 3. Check the result

The Receive tab fills in Filename, Size, SHA256 and both verdicts:
`Size match PASS` and `SHA256 match PASS`. The file lands in the configured
receive folder, never overwriting: a second copy becomes `name (1).ext`.
Use **Compare with original...** to diff SHA256 against the source file.

![Receive page](https://raw.githubusercontent.com/FattyFussCODES/DNSmuggle/main/docs/screenshots/lab-receive.png)

## Install and run

Python **3.11+** and Tkinter are required for the main application (on
Debian/Ubuntu, install `python3-tk`). The optional workbench uses `pywebview`
and needs Microsoft Edge WebView2 on Windows or WebKitGTK on Linux
(`python3-gi` and `gir1.2-webkit2-4.1` on Debian/Ubuntu). `cryptography`
supports transfer encryption; `reportlab` is optional for PDF reports.

From a source checkout, install the main application in editable mode and run
it from the repository root:

```bash
python -m pip install -e .
dnsmuggle
```

To add the optional workbench and PDF report support:

```bash
python -m pip install -e ".[workbench,pdf]"
dnsmuggle-workbench
```

For development and tests, run `python -m pip install -e ".[dev]"` or
`python -m pip install -r requirements.txt` from the repository root; both
install the project in editable mode with test dependencies. Extras can be
combined, for example `python -m pip install -e ".[dev,workbench,pdf]"`.

The frontend source is the distributable `app/workbench/web/` directory.
It uses browser modules directly: no Node installation or frontend build step
is needed. Keep its HTML, scripts, styles, icons, fonts and license files
together when packaging. Build Python distributions only after those files are
present; neither local credentials nor application data belong in an artifact.

For a non-editable installation from the current source tree:

```bash
python -m pip install .
dnsmuggle
```

To install the latest published release instead, run:

```bash
python -m pip install dnsmuggle
```

Add the optional workbench with `python -m pip install "dnsmuggle[workbench]"`.
The PyPI release may differ from this source checkout.

The workbench defaults to `127.0.0.1:15353`. A port already in use produces
a bind error; stop the other listener or select a free port. Binding port 53
may require administrator privileges. The lab's receiver and the workbench
cannot bind the same address and port at the same time.

## Data and privacy

The workbench stores `workbench.db` and generated reports in the `workbench`
subdirectory of `platformdirs.user_data_path("DNSMuggle", appauthor=False)`.
The main application uses that platform-specific DNSMuggle data directory for its
own configuration and default files. The exact location depends on the OS and
environment. Query names and source addresses are stored as observation
metadata and may be sensitive; protect the data directory and review reports
before sharing. Keep credentials, local configuration, received files, and
databases out of source and distribution artifacts.
On first launch, legacy lab data in the source-tree application directory and
workbench data in `~/DNSMuggle/workbench` are copied to the corresponding
per-user locations when applicable. Existing destination data is not replaced;
the original data remains in place. A conflicting workbench report stops
migration so the conflict can be resolved without losing either copy.

## How it works

```
your file ──> encoder ── DNS queries ──> decoder ──> recovered file
                │  001.<chunk>.<session>.dnstunnel.cc.cd
                │  002.<chunk>.<session>.dnstunnel.cc.cd
                │  END.<session>.dnstunnel.cc.cd
```

1. Read the file as bytes, not text, so text, PNGs and zips all work.
2. Compress with zlib level 6 when the payload is over 1 KB (flagged in the
   header), then encrypt with Fernet when a password is set (also flagged).
3. Build the stream: header JSON + `\n` + the processed bytes. `size` and
   `sha256` describe the **original** file, so verification is end to end.
4. Base32-encode the stream and cut it into chunks of 16–63 characters
   (32 by default), numbered `001, 002, ...`. Each query carries one chunk.
5. Send up to 10 queries before collecting their individual matching-QID
   ACKs. Retry only missing chunks on timeout (max 3 attempts, 2.0 s each).
6. Send one `END` query. The decoder sorts chunks **numerically**, decodes
   them, reverses encrypt/decompress, and checks size and SHA256 against the
   header.

Hand-built DNS packets only: `socket` + `struct`, no DNS library anywhere.

### Real chunk counts

The header carries the filename, a 64-character hex SHA256, flags and the
chunk count, so a small file costs more queries than its size suggests.
These counts use the default 32-character chunk size.

| File | Chunks |
|---|---|
| 15 B | 10 |
| 346 B (`examples/Neo4j-...txt`) | 28 |
| 1 KB, uncompressed | 61 |
| 4 KB of `A`, compressed | 11 |

The GUI previews this before you send, from the real stream, never a guess.

## Project structure

```
DNSMuggle/
├── app/
│   ├── main.py                 # main transfer and detection entry point
│   ├── lab_main.py             # Tkinter transfer and detection window
│   ├── workbench/              # monitor, storage, reports, local bridge and web UI
│   ├── protocol.py             # packets, chunking, ACK/retry/END, Receiver
│   ├── crypto.py               # Fernet + PBKDF2, XOR+HMAC fallback
│   ├── detector.py             # length, entropy and rate rules
│   ├── config.py               # transfer lab configuration
│   ├── assets/                 # application graphics
│   └── gui/                    # original five-tab lab window
├── encoder.py                  # CLI wrapper over app.protocol
├── decoder.py                  # CLI wrapper over app.protocol
├── dns_topo.py                 # Mininet topology: h1, h2, s1
├── tests/                      # pytest suite
├── examples/
│   ├── secret.txt              # "Meet at 5"
│   └── Neo4j-c07dc072-Created-2026-04-27.txt  # 346 B, 28 chunks
├── docs/
│   ├── PROTOCOL.md             # packets, stream, layers, limits
│   ├── DEMO_SKEIN.md           # Skein mesh demo script
│   ├── PORT_FORWARDING_TEST.md # public relay test
│   ├── TWO_LAPTOP_SETUP.md     # same-Wi-Fi test
│   ├── VM_DEPLOY.md            # permanent decoder VM
│   └── screenshots/            # logo + Send/Receive screenshots
├── requirements.txt
├── pyproject.toml              # pip install . -> "dnsmuggle" command
└── README.md
```

## Command line (source checkout)

The legacy transfer lab uses the same library as these source-tree wrappers.
`encoder.py` and `decoder.py` are not installed as separate wheel commands.

```bash
# Terminal 1
python decoder.py --host 127.0.0.1 --port 15353

# Terminal 2
python encoder.py examples/secret.txt --server 127.0.0.1 --port 15353 --delay 0.01 --chunk-size 32
```

Both accept `--password` and `--domain`; only the encoder accepts
`--no-compress`. The decoder writes `recovered_<filename>`; the lab GUI uses
its configured receive folder.

## Tests

```bash
python -m pytest tests/ -v
```

The suite covers protocol and chunking, selective ACK retries, UDP loopback,
encryption, detection and reports.


## Main application pages

- **Send** — file, real chunk/time estimate, 16–63-character chunk-size
  slider, 10-chunk ACK windows, delay slider, optional password, live log,
  progress with chunks/sec and ETA, Cancel. The log retains the newest 4,000
  lines; labels over 40 characters trigger the detector's length rule.
- **Receive** — host/port, start/stop, live chunk table with the actual
  queries, size/SHA256 verdicts, open file/folder, compare with original.
  The log also retains the newest 4,000 lines.
- **History** — every send and receive recorded in the lab's SQLite history:
  date, filename, size, session, server, mode, chunks, result, time taken.
  Refresh, clear, export CSV, generate a report.
- **Detector** — a passive tap on the **Receive tab's** listener: one socket,
  no second bind, so it can watch the same port as the receiver. Length,
  entropy and rate rules, queries-per-second chart on a Canvas, alerts list,
  and a "Possible DNS tunnelling detected" banner when two or more rules fire
  within 60 seconds. **Start monitoring** starts that shared listener if it
  is not running; **Stop monitoring** only detaches, the receiver keeps
  listening. Two self-tests: real encoder chunks get flagged, ordinary DNS
  names pass.
- **Settings** — defaults, transport mode, receiver folder, history path,
  and About (with logo). Domain mode requires a user confirmation; the app
  does not independently verify the public relay test.

## Known limits

- **Encryption only when a password is set.** Left blank, chunks are Base32
  and anyone on the path can read them. With a password: Fernet + PBKDF2
  (200 000 iterations, random salt per message).
- At the default chunk size each query carries approximately 20 stream bytes;
  changing the size trades fewer queries for longer, more detectable labels.
- UDP only, no resume: a decoder restart loses the in-memory session.
- Receiver sessions and input sizes are not bounded; the receiver can consume
  substantial memory. It writes reconstructed files even if the reported
  size or SHA-256 comparison fails. The sender's success result does not
  establish successful reconstruction.
- DNS-over-HTTPS would bypass this channel entirely.
- Easy to flag with length, entropy and rate heuristics at high speed — which
  is exactly what the Detector tab demonstrates.
- The workbench observes only DNS queries delivered to its own UDP endpoint.
  It does not share the lab receiver's socket or observe network-wide traffic;
  its listener does not send the ACKs required by the transfer tools.

## Safety

Lab only: your own machines, your own files, your own decoder. There is no
scanning, no exfiltration helper, and no target list.

## License

MIT. See `LICENSE`.
