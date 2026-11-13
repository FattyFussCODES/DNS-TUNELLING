# DNSMuggle

DNSMuggle is a desktop lab for exploring how data can be carried in DNS
queries and how that traffic can be detected. Send and receive your own
files, inspect the queries, and verify the recovered file.

> **Use only in an authorized lab:** your own files, machines, and network.

## Install

Requires Python 3.11 or newer.

```bash
pip install dnsmuggle
```

Start the application:

```bash
dnsmuggle
```

On Linux, install Tkinter if it is not already available (for example,
`sudo apt install python3-tk` on Debian or Ubuntu). If `dnsmuggle` is not
recognized, try `python -m app.main` with the Python installation used for
`pip`.

## Try it on one computer

1. Open **Receive**. Keep the host as `127.0.0.1` and port as `5353`, then
   select **Start**. If that port is busy, choose another available port.
2. Open **Send**, choose a file you own, and select the **Loopback** preset.
   Use the same port as the receiver, then select **Send**.
3. Return to **Receive** to see the recovered file and the size and SHA-256
   results. Use **Compare with original** for an additional check.

To test between your own computers, enter the receiver's address and the same
port on the sender. Only use networks and machines you are authorized to use.

## What's in the app

- **Send:** choose a file, review its chunk count, and send it.
- **Receive:** run the listener, inspect incoming chunks, and recover files.
- **History:** review transfers and export results.
- **Detector:** observe the receiver's queries using length, entropy, and
  rate rules. It only sees traffic delivered to that listener.
- **Settings:** configure the application and storage locations.

Password encryption is optional. Without a password, Base32 is encoding, not
encryption; DNS query metadata remains visible even with encryption enabled.
PDF reports require the optional extra: `pip install "dnsmuggle[pdf]"`.

## Troubleshooting

- **Port in use:** choose another port in both Receive and Send.
- **Cannot connect:** start the receiver first, check the address and port, and
  confirm your firewall allows the authorized test.
- **Encrypted file cannot be read:** enter the same password on both sides
  before starting the receiver and sending.

The receiver is intended for a controlled lab. It keeps sessions in memory,
has no resume after a restart, and saves a reconstructed file even when its
size or hash check fails. Sender success alone does not prove the receiver
recovered the file.

## More information

- [Wire protocol and limits](https://github.com/FattyFussCODES/DNSmuggle/blob/main/docs/PROTOCOL.md)
- [Two-computer setup](https://github.com/FattyFussCODES/DNSmuggle/blob/main/docs/TWO_LAPTOP_SETUP.md)
- [Source code](https://github.com/FattyFussCODES/DNSmuggle)

MIT license.
