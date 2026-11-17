# Tiny chess v5 (MIT). 0x88 board. Eval: material + formula PSTs + bishop
# pair. Search: PVS + quiescence + TT + iterative deepening, node cap.
# Quiescence has a depth guard (QMAX): without it a capture-rich position
# explodes to the node cap, no depth completes, and the first legal move wins.
import json, os, sys, urllib.request, urllib.error

ENV = os.environ.get("MAKEFUN_ENV_URL") or sys.exit("MAKEFUN_ENV_URL is not set")

VAL = [0, 100, 320, 330, 500, 900, 20000]
def _cen(i):
    return i if i < 4 else 7 - i
_PA = [0, 0, 4, 8, 14, 24, 40, 0]
_PC = [0, 0, 0, 10, 15, 10, 5, 0]
_KMG = [20, 25, 10, 0, 0, 10, 25, 20]
PST = {t: [0] * 128 for t in range(1, 7)}
for _sq in range(128):
    if _sq & 0x88:
        continue
    _r = 7 - (_sq >> 4)
    _f = _sq & 7
    _c = _cen(_f) + _cen(_r)
    PST[1][_sq] = _PA[_r] + (_PC[_r] if _f in (3, 4) else 0)
    PST[2][_sq] = 6 * _c - 20
    PST[3][_sq] = 4 * _c - 8
    PST[4][_sq] = (15 if _r == 6 else 0) + (5 if _r == 0 and _f in (3, 4) else 0)
    PST[5][_sq] = 2 * _c - 6
    PST[6][_sq] = _KMG[_f] if _r == 0 else max(-50, -15 * _r)
# 0x88 offsets. Rook order keeps v4's (up, down, left, right): any other
# order makes quiescence 4x slower on the same position.
KN = [-33, -31, -18, -14, 14, 18, 31, 33]
BI = [-17, -15, 15, 17]
RO = [-16, 16, -1, 1]
KI = BI + RO
DIRS = {2: KN, 3: BI, 4: RO, 5: KI, 6: KI}
SLIDE = {3, 4, 5}
# Zobrist keys, deterministic LCG: 13 piece slots x 128 squares + side
Z = []
_x = 1
for _ in range(13 * 128 + 1):
    _x = (_x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
    Z.append(_x)
ZS = Z[13 * 128]

NODES = [0]
NODE_CAP = 22000
# Quiescence depth guard: past QMAX the static eval stands, even in check.
# 8 keeps every move inside the 10s limit; 16 saw deeper but forfeited
# two games on time in the local gauntlet (moves over 10s).
QMAX = 8
class Abort(Exception):
    pass
H = [0]
T = {}
KILL = [[] for _ in range(64)]
HIST = {}
WK = [116]
BK = [4]

def parse(fen):
    parts = fen.split()
    B = [0] * 128
    mp = {'P':1,'N':2,'B':3,'R':4,'Q':5,'K':6,'p':-1,'n':-2,'b':-3,'r':-4,'q':-5,'k':-6}
    r = f = 0
    for ch in parts[0]:
        if ch == '/':
            r += 1; f = 0
        elif ch.isdigit():
            f += int(ch)
        else:
            B[r*16+f] = mp[ch]; f += 1
    side = 1 if parts[1] == 'w' else -1
    cast = parts[2] if len(parts) > 2 else '-'
    ep = parts[3] if len(parts) > 3 and parts[3] != '-' else None
    epsq = None
    if ep:
        epsq = (8-int(ep[1]))*16 + (ord(ep[0])-97)
    for sq in range(128):
        if B[sq] == 6:
            WK[0] = sq
        elif B[sq] == -6:
            BK[0] = sq
    H[0] = 0
    for sq in range(128):
        if not sq & 0x88 and B[sq]:
            H[0] ^= Z[(B[sq]+6)*128+sq]
    if side < 0:
        H[0] ^= ZS
    return B, side, cast, epsq

def sq_name(sq):
    return "abcdefgh"[sq & 7] + str(8 - (sq >> 4))

def gen_moves(B, side, cast, epsq):
    moves = []
    for sq in range(128):
        p = B[sq]
        if p == 0 or (p > 0) != (side > 0):
            continue
        t = abs(p)
        if t == 1:
            d = -16 if side > 0 else 16
            start = 6 if side > 0 else 1
            last = 0 if side > 0 else 7
            one = sq + d
            if not one & 0x88 and B[one] == 0:
                if one >> 4 == last:
                    for pr in (5, 4, 3, 2):
                        moves.append((sq, one, pr))
                else:
                    moves.append((sq, one, 0))
                two = sq + d * 2
                if (sq >> 4) == start and B[two] == 0:
                    moves.append((sq, two, 0))
            for df in (-1, 1):
                to = sq + d + df
                if to & 0x88:
                    continue
                if B[to] != 0 and (B[to] > 0) != (side > 0):
                    if to >> 4 == last:
                        for pr in (5, 4, 3, 2):
                            moves.append((sq, to, pr))
                    else:
                        moves.append((sq, to, 0))
                elif epsq is not None and to == epsq:
                    moves.append((sq, to, 0))
        else:
            for off in DIRS[t]:
                nsq = sq
                while True:
                    nsq += off
                    if nsq & 0x88:
                        break
                    q = B[nsq]
                    if q == 0:
                        moves.append((sq, nsq, 0))
                    else:
                        if (q > 0) != (side > 0):
                            moves.append((sq, nsq, 0))
                        break
                    if t not in SLIDE:
                        break
    if side > 0:
        if 'K' in cast and B[117] == 0 and B[118] == 0 and B[116] == 6:
            moves.append((116, 118, 0))
        if 'Q' in cast and B[115] == 0 and B[114] == 0 and B[113] == 0 and B[116] == 6:
            moves.append((116, 114, 0))
    else:
        if 'k' in cast and B[5] == 0 and B[6] == 0 and B[4] == -6:
            moves.append((4, 6, 0))
        if 'q' in cast and B[3] == 0 and B[2] == 0 and B[1] == 0 and B[4] == -6:
            moves.append((4, 2, 0))
    return moves

def do_move(B, frm, to, promo, epsq):
    p = B[frm]
    cap = B[to]
    was_ep = False
    rook = None
    H[0] ^= Z[(p+6)*128+frm]
    if cap:
        H[0] ^= Z[(cap+6)*128+to]
    if abs(p) == 1 and epsq is not None and to == epsq and cap == 0:
        cap_sq = to + (16 if p > 0 else -16)
        cap = B[cap_sq]
        B[cap_sq] = 0
        H[0] ^= Z[(cap+6)*128+cap_sq]
        was_ep = True
    B[frm] = 0
    np = (promo if promo else abs(p)) * (1 if p > 0 else -1)
    B[to] = np
    H[0] ^= Z[(np+6)*128+to]
    if abs(p) == 6:
        if p > 0:
            WK[0] = to
        else:
            BK[0] = to
    if abs(p) == 6 and abs(to - frm) == 2:
        if to > frm:
            rs, rt = frm + 3, frm + 1
        else:
            rs, rt = frm - 4, frm - 1
        rook = (rs, rt, B[rs])
        H[0] ^= Z[(B[rs]+6)*128+rs]
        B[rt] = B[rs]
        B[rs] = 0
        H[0] ^= Z[(B[rt]+6)*128+rt]
    H[0] ^= ZS
    return p, cap, was_ep, rook

def undo_move(B, frm, to, promo, p, cap, was_ep, rook, epsq):
    np = B[to]
    H[0] ^= Z[(np+6)*128+to]
    B[frm] = p
    B[to] = 0
    H[0] ^= Z[(p+6)*128+frm]
    if abs(p) == 6:
        if p > 0:
            WK[0] = frm
        else:
            BK[0] = frm
    if was_ep:
        cap_sq = to + (16 if p > 0 else -16)
        B[cap_sq] = cap
        H[0] ^= Z[(cap+6)*128+cap_sq]
    elif cap:
        B[to] = cap
        H[0] ^= Z[(cap+6)*128+to]
    if rook:
        rs, rt, rp = rook
        B[rs] = rp
        B[rt] = 0
        H[0] ^= Z[(rp+6)*128+rt]
        H[0] ^= Z[(rp+6)*128+rs]
    H[0] ^= ZS

def in_check(B, side):
    ksq = WK[0] if side > 0 else BK[0]
    return attacked(B, ksq, -side)

def attacked(B, sq, by):
    for df in (-1, 1):
        t = sq + (16 if by > 0 else -16) + df
        if not t & 0x88 and B[t] == by:
            return True
    for t, dirs in DIRS.items():
        if t == 1:
            continue
        for off in dirs:
            nsq = sq
            while True:
                nsq += off
                if nsq & 0x88:
                    break
                q = B[nsq]
                if q != 0:
                    if (q > 0) == (by > 0) and abs(q) == t:
                        return True
                    break
                if t not in SLIDE:
                    break
    return False

def legal_moves(B, side, cast, epsq):
    out = []
    for (frm, to, pr) in gen_moves(B, side, cast, epsq):
        p, cap, ep, rk = do_move(B, frm, to, pr, epsq)
        if not in_check(B, side):
            out.append((frm, to, pr))
        undo_move(B, frm, to, pr, p, cap, ep, rk, epsq)
    return out

def evaluate(B):
    s = 0
    wb = bb = 0
    for sq in range(128):
        if sq & 0x88:
            continue
        p = B[sq]
        if p == 0:
            continue
        t = abs(p)
        v = VAL[t] + PST[t][sq if p > 0 else sq ^ 0x70]
        s += v if p > 0 else -v
        if t == 3:
            if p > 0:
                wb += 1
            else:
                bb += 1
    if wb >= 2:
        s += 30
    if bb >= 2:
        s -= 30
    return s

def order_moves(B, moves, ply, ttm=None):
    kl = KILL[ply] if ply < 64 else []
    def sc(m):
        if ttm is not None and m == ttm:
            return 2000000
        frm, to, pr = m
        v = B[to]
        if v:
            return 1000000 + VAL[abs(v)] * 10 - VAL[abs(B[frm])]
        if pr:
            return 900000 + VAL[pr]
        if m in kl:
            return 800000
        return HIST.get((frm, to), 0)
    moves.sort(key=sc, reverse=True)
    return moves

def quiesce(B, side, alpha, beta, qd=0):
    NODES[0] += 1
    if NODES[0] > NODE_CAP:
        raise Abort
    check = in_check(B, side)
    if not check:
        stand = evaluate(B) * side + 10
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
    # Guard: past QMAX the static eval stands, even in check.
    if qd >= QMAX:
        return alpha if not check else evaluate(B) * side + 10
    if check:
        alpha = -10**9
    legal = 0
    for (frm, to, pr) in legal_moves(B, side, '', None):
        if not check and B[to] == 0 and not (abs(B[frm]) == 1 and to >> 4 in (0, 7)):
            continue
        p, cap, ep, rk = do_move(B, frm, to, pr, None)
        sc = -quiesce(B, -side, -beta, -alpha, qd + 1)
        undo_move(B, frm, to, pr, p, cap, ep, rk, None)
        if sc >= beta:
            return beta
        if sc > alpha:
            alpha = sc
        legal += 1
    if check and legal == 0:
        return -20000
    return alpha

def search(B, side, depth, alpha, beta, ply):
    NODES[0] += 1
    if NODES[0] > NODE_CAP:
        raise Abort
    if depth == 0:
        return quiesce(B, side, alpha, beta)
    a0 = alpha
    e = T.get(H[0])
    ttm = None
    if e and e[0] >= depth:
        _, fl, sc, bm = e
        if fl == 0:
            return sc
        if fl == 1:
            if sc >= beta:
                return beta
            if sc > alpha:
                alpha = sc
        else:
            if sc <= alpha:
                return alpha
            if sc < beta:
                beta = sc
        ttm = bm
    moves = legal_moves(B, side, '', None)
    if not moves:
        return -20000 - depth if in_check(B, side) else 0
    order_moves(B, moves, ply, ttm)
    best = moves[0]
    for i, (frm, to, pr) in enumerate(moves):
        p, cap, ep, rk = do_move(B, frm, to, pr, None)
        if i == 0:
            sc = -search(B, -side, depth - 1, -beta, -alpha, ply + 1)
        else:
            sc = -search(B, -side, depth - 1, -alpha - 1, -alpha, ply + 1)
            if alpha < sc < beta:
                sc = -search(B, -side, depth - 1, -beta, -alpha, ply + 1)
        undo_move(B, frm, to, pr, p, cap, ep, rk, None)
        if sc >= beta:
            if not cap and not pr:
                kl = KILL[ply]
                if (frm, to, pr) not in kl:
                    KILL[ply] = [(frm, to, pr)] + kl[:1]
                HIST[(frm, to)] = HIST.get((frm, to), 0) + depth * depth
            T[H[0]] = (depth, 1, sc, (frm, to, pr))
            return beta
        if sc > alpha:
            alpha = sc
            best = (frm, to, pr)
    T[H[0]] = (depth, 2 if alpha <= a0 else 0, alpha, best)
    return alpha

def best_move(fen, legal_uci):
    B, side, cast, epsq = parse(fen)
    def uci_to_move(u):
        frm = (8 - int(u[1])) * 16 + (ord(u[0]) - 97)
        to = (8 - int(u[3])) * 16 + (ord(u[2]) - 97)
        pr = {'q': 5, 'r': 4, 'b': 3, 'n': 2}.get(u[4], 0) if len(u) == 5 else 0
        return (frm, to, pr)
    moves = [uci_to_move(u) for u in legal_uci]
    best = moves[0]
    NODES[0] = 0
    for depth in range(1, 7):
        try:
            cur_best, cur_sc = moves[0], -10**9
            alpha = -10**9
            for m in moves:
                p, cap, ep, rk = do_move(B, m[0], m[1], m[2], epsq)
                sc = -search(B, -side, depth - 1, -10**9, -alpha, 1)
                undo_move(B, m[0], m[1], m[2], p, cap, ep, rk, epsq)
                if sc > cur_sc:
                    cur_sc, cur_best = sc, m
                if sc > alpha:
                    alpha = sc
            best = cur_best
        except Abort:
            break
    frm, to, pr = best
    u = sq_name(frm) + sq_name(to)
    if pr:
        u += 'qrbn'[5 - pr] if pr == 5 else {4: 'r', 3: 'b', 2: 'n'}[pr]
    return u

def post(path, body):
    req = urllib.request.Request(
        ENV + path, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        sys.exit(f"{path}: HTTP {e.code}")

while True:
    g = post("/game", {})
    if g["status"] == "done":
        break
    while g["status"] == "your_move":
        g = post("/move", {"game": g["game"],
                           "move": best_move(g["fen"], g["legal_moves"])})
    print(f"game {g['game']}: {g['outcome']} by {g['reason']}", file=sys.stderr)
print(f"done: {g.get('wins')} won, {g.get('draws')} drawn, {g.get('losses')} lost", file=sys.stderr)
