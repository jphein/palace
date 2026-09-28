# The demo palace is synthetic

`seed.jsonl` is a **made-up** memory archive for a fictional person who runs a fictional
community tech hub ("Juniper Street Tech Hub"). No entry comes from a real person's memory.
It contains deliberate texture for the demo:

- a decision that is later **reversed** (hire a coordinator in July, cancelled in August), for
  Ultra-tier "what did I decide, and did it change?" questions;
- **promises with dates** (quarterly county reports), for "what do I owe, and when?";
- **lessons learned** (SMART-check donated laptops, 18pt guides), for recall with citations.

Without `PALACE_URL` the app searches this file directly (BM25, offline). To load it into a
**separate, throwaway** palace-daemon instance, run `python demo/load_demo.py http://127.0.0.1:8085`.
The loader, like the app, refuses hosts that serve a real personal palace: your deny-list, plus anything that looks
like a home/LAN server (see the guard in the top-level README). Loopback is allowed. A demo daemon on a LAN address
must be listed in `PALACE_ALLOW_HOSTS`.
