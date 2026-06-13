#!/usr/bin/env bash
#
# record-demo.sh — scripted terminal demo that proves Scribe's three claims.
#
# It plays a fixed scenario of REAL commands against your llama-server, so the
# resulting recording is honest (no faked output). Each scene maps to one claim:
#
#   1. tool calls that can't break   — GBNF grammar produces a valid call
#   2. cite or refuse                — grounded answers cite [n] / refuse
#   3. grounding is measured         — scribe bench reports a deterministic SPI
#
# USAGE
#   ./promo/record-demo.sh            play the demo in this terminal
#   ./promo/record-demo.sh --check    quick prerequisite check, no playback
#
# RECORD IT (asciinema -> gif)
#   asciinema rec -c ./promo/record-demo.sh promo/demo.cast
#   agg promo/demo.cast promo/demo.gif        # asciinema gif generator
#
# TUNING (env)
#   PACE=0.03    per-character typing delay (0 = instant)
#   PAUSE=1.6    seconds to linger after each command's output
#
set -uo pipefail

PACE="${PACE:-0.03}"
PAUSE="${PAUSE:-1.6}"
SCRIBE="${SCRIBE:-scribe}"
PROMPT="\033[1;36mscribe-demo\033[0m$ "

command -v "$SCRIBE" >/dev/null 2>&1 || SCRIBE="python3 -m scribe.cli"

# ── helpers ────────────────────────────────────────────────────────────────
type_out() {  # simulate a human typing a command
  local text="$1" ch
  printf "%b" "$PROMPT"
  for ((i = 0; i < ${#text}; i++)); do
    ch="${text:i:1}"
    printf "%s" "$ch"
    [ "$PACE" != "0" ] && sleep "$PACE"
  done
  printf "\n"
}

run() {  # type a command, then actually run it, then linger
  type_out "$1"
  eval "$1"
  echo
  sleep "$PAUSE"
}

say() {  # an on-screen comment line (cyan), not a command
  printf "\033[0;36m# %b\033[0m\n" "$1"
  sleep 0.9
}

scene() {  # scene header
  printf "\n\033[1;33m── %s ──\033[0m\n\n" "$1"
  sleep 0.8
}

# ── prerequisites ────────────────────────────────────────────────────────────
check() {
  echo "Checking prerequisites…"
  if $SCRIBE status >/dev/null 2>&1; then
    echo "  ok  scribe runs ($SCRIBE)"
  else
    echo "  !!  scribe not runnable — install with ./scripts/install.sh"; return 1
  fi
  if $SCRIBE status --json 2>/dev/null | grep -q '"reachable": true'; then
    echo "  ok  model server reachable"
  else
    echo "  !!  model server not reachable — start llama-server first"; return 1
  fi
  command -v asciinema >/dev/null 2>&1 \
    && echo "  ok  asciinema present (can record)" \
    || echo "  --  asciinema not installed (playback only; 'pip install asciinema' to record)"
  echo "Ready."
}

# ── the scenario ──────────────────────────────────────────────────────────────
play() {
  clear
  printf "\033[1;35m"
  cat <<'BANNER'
   ┌─────────────────────────────────────────────┐
   │  Scribe — a local agent that doesn't bluff   │
   └─────────────────────────────────────────────┘
BANNER
  printf "\033[0m\n"
  sleep 1.5

  scene "Capabilities"
  say "Grammar enforcement and the sandbox are on by default."
  run "$SCRIBE status"

  scene "Claim 1 — the tool call cannot break"
  say "A GBNF grammar is built from the tool schemas. Under it, the model"
  say "can only emit a VALID call — a malformed tool call is impossible."
  run "python3 promo/_demo_grammar.py"

  scene "Claim 2 + 3 — cite or refuse, and it's measured"
  say "scribe bench runs a checksum-locked grounded suite: answerable tasks"
  say "must cite their sources [n], impossible ones must be refused."
  run "$SCRIBE bench --spi"

  scene "Try it yourself"
  say "git clone https://github.com/pedjaurosevic/scribe-ai"
  say "Local-first · ~7k lines · 250+ tests · MIT"
  sleep 2
}

# ── entry ─────────────────────────────────────────────────────────────────────
case "${1:-}" in
  --check) check ;;
  --help|-h) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) play ;;
esac
