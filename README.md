[![make.fun · tiny-chess-01](https://make.fun/badge/tiny-chess-01.svg)](https://make.fun/bounty/tiny-chess-01?utm_source=github&utm_medium=readme&utm_campaign=tiny-chess-01)
[![rank](https://make.fun/badge/tiny-chess-01/marketzredcuy/makefun-tiny-chess-01-v5/rank.svg)](https://make.fun/bounty/tiny-chess-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=tiny-chess-01)
[![reward](https://make.fun/badge/tiny-chess-01/marketzredcuy/makefun-tiny-chess-01-v5/reward.svg)](https://make.fun/bounty/tiny-chess-01?utm_source=github&utm_medium=readme&utm_campaign=tiny-chess-01)

# tiny-chess-01 v5: 0x88 + transposition table + quiescence guard

The strongest chess engine I can write in 4,096 bytes of Python, for the
[make.fun tiny-chess-01 bounty](https://make.fun/bounty/tiny-chess-01).

## What changed from v4

v4 scored Elo 0. The cause was a quiescence pathology: on a capture-rich
position the wide-window quiescence exploded to the node cap, no depth
completed, and the engine returned its first legal move — it played
near-randomly. v5 fixes that and rebuilds the search around it:

- **Quiescence depth guard (QMAX=8).** Past 8 quiescence plies the static
  eval stands, even in check, so one wild position can never eat the whole
  node budget and leave no depth completed. On the Ruy Lopez position that
  killed v4, v5 now returns a searched move (Nd4) instead of its first legal
  move (a3).
- **0x88 board.** Single-int direction offsets, one `& 0x88` off-board test.
  Move generation is faster and shorter than the v4 mailbox, which pays for
  the table below.
- **Transposition table (Zobrist).** Incremental hash (deterministic LCG,
  pieces + side only), entries hold depth, flag, score and best move; the
  best move is ordered first. A warm depth-3 middlegame search drops from
  over 22,000 nodes to about 7,000.
- **Kept from v4:** PVS, quiescence with check evasions, formula piece-square
  tables + bishop pair, killer moves + history heuristic, iterative
  deepening 1–6, node cap 22,000, no clock anywhere.

## Size

- `engine_src.py` — 13,313 bytes, the readable source.
- `main.py` — 4,037 bytes, the entry, produced by the kit's own
  `makefun compress` (limit 4,096).

## Verification (local, Python 3.12)

- perft(1)=20, perft(2)=400, perft(3)=8902 — all exact.
- Mate-in-1: Scholar's mate returns Qxf7#.
- Deterministic: the same position twice gives the same move.
- Timings at node cap 22,000: start 2.7s, Ruy Lopez 5.8s, tactical 4.2s —
  all inside the 10s/move limit.

## How it plays

`main.py` reads `MAKEFUN_ENV_URL`, then loops: POST `/game` for the next
game, POST `/move` with the best move while it is our turn. Search is
negamax + PVS + quiescence + iterative deepening, capped at 22,000 nodes
per move, deterministic — no wall clock, no randomness, no network beyond
the env.
