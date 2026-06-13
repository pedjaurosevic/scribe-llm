# promo/ — launch assets

Files used to produce and run the Scribe launch.

- **`source.md`** — the canonical launch text. Every channel (Show HN,
  r/LocalLLaMA, dev.to, X/Bluesky, YouTube description) is trimmed from this
  one file. Edit here, never embellish per channel.
- **`record-demo.sh`** — a scripted terminal demo that runs REAL commands and
  proves the three claims (unbreakable tool calls, cite-or-refuse, measured SPI).
- **`_demo_grammar.py`** — helper for the demo's claim-1 scene.

## Make the demo GIF

```bash
# 1. sanity check (needs a running llama-server)
./promo/record-demo.sh --check

# 2. record (pip install asciinema first)
asciinema rec -c ./promo/record-demo.sh promo/demo.cast

# 3. turn it into a GIF (pip install / cargo install agg)
agg promo/demo.cast promo/demo.gif
```

Tuning: `PACE=0.03` (typing speed), `PAUSE=1.6` (linger after each command).
Run `PACE=0 PAUSE=0 ./promo/record-demo.sh` for an instant dry run.

The demo writes nothing outside the repo and touches none of your data — it
only reads status and runs the bundled bench. See `../Desktop/scribe-promo.md`
(local, not committed) for the full campaign plan.
