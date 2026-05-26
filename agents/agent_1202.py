import math
import time
from collections import deque
from player_hex import PlayerHex
from seahorse.game.action import Action
from seahorse.game.game_state import GameState
from seahorse.game.stateless_action import StatelessAction

# Hex Agent — Minimax + Alpha-Beta + Yang et al. (FSKD 2007) Heuristics
#
# Knowledge structures from the paper:
#   - ConnectedString  : group of same-color stones + border relationship
#   - VirtualConnection: bridge / ziggurat patterns with carrier sets
#   - Group            : string cluster reachable via virtual connections
#   - 13 move-gen rules: prioritised candidate generation (Section 4)
#
# Evaluation function (no ML):
#   score = opp_d1 - my_d1                     (primary path advantage)
#         + 0.5 * (opp_d2 - my_d2)             (two-distance bonus)
#         + 0.3 * virtual_connection_advantage  (VC count difference)
#         + 0.2 * group_border_advantage        (groups touching borders)


# ======================================================================
# Constants
# ======================================================================

HEX_DIRS = [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)]

ST_NONE      = 0
ST_TOP       = 1   # touches source edge  (row 0 for R, col 0 for B)
ST_BOTTOM    = 2   # touches target edge  (row dim_x-1 for R, col dim_y-1 for B)
ST_TOPBOTTOM = ST_TOP | ST_BOTTOM  # winning connection


# ======================================================================
# Lightweight board piece
# ======================================================================

class _FakePiece:
    __slots__ = ("piece_type",)
    def __init__(self, piece_type: str):
        self.piece_type = piece_type


# ======================================================================
# Board helpers
# ======================================================================

def _in_bounds(r, c, dim_x, dim_y) -> bool:
    return 0 <= r < dim_x and 0 <= c < dim_y


def _shortest_path(env: dict, dim_x: int, dim_y: int, color: str) -> float:
    """0-1 BFS shortest connecting path. Own stone=0, empty=1, opponent=blocked."""
    INF = math.inf
    if color == "R":
        sources      = [(0, c) for c in range(dim_y)]
        target_check = lambda r, c: r == dim_x - 1
    else:
        sources      = [(r, 0) for r in range(dim_x)]
        target_check = lambda r, c: c == dim_y - 1

    dist = {}
    dq   = deque()
    for pos in sources:
        p = env.get(pos)
        if p and p.piece_type != color:
            continue
        cost = 0 if p else 1
        if cost < dist.get(pos, INF):
            dist[pos] = cost
            dq.appendleft((cost, pos)) if cost == 0 else dq.append((cost, pos))

    while dq:
        d, (r, c) = dq.popleft()
        if d > dist.get((r, c), INF):
            continue
        if target_check(r, c):
            return d
        for dr, dc in HEX_DIRS:
            nr, nc = r + dr, c + dc
            if not _in_bounds(nr, nc, dim_x, dim_y):
                continue
            p = env.get((nr, nc))
            if p and p.piece_type != color:
                continue
            cost = 0 if p else 1
            nd   = d + cost
            if nd < dist.get((nr, nc), INF):
                dist[(nr, nc)] = nd
                dq.appendleft((nd, (nr, nc))) if cost == 0 else dq.append((nd, (nr, nc)))
    return INF


def _second_shortest_path(env: dict, dim_x: int, dim_y: int,
                           color: str, d1: float) -> float:
    """Shortest path after blocking all empty cells on the first shortest path."""
    INF = math.inf
    if d1 == INF:
        return INF

    def bfs(srcs):
        dist = {}
        dq   = deque()
        for pos in srcs:
            p = env.get(pos)
            if p and p.piece_type != color:
                continue
            cost = 0 if p else 1
            if cost < dist.get(pos, INF):
                dist[pos] = cost
                dq.appendleft((cost, pos)) if cost == 0 else dq.append((cost, pos))
        while dq:
            d, (r, c) = dq.popleft()
            if d > dist.get((r, c), INF):
                continue
            for dr, dc in HEX_DIRS:
                nr, nc = r + dr, c + dc
                if not _in_bounds(nr, nc, dim_x, dim_y):
                    continue
                p = env.get((nr, nc))
                if p and p.piece_type != color:
                    continue
                cost = 0 if p else 1
                nd   = d + cost
                if nd < dist.get((nr, nc), INF):
                    dist[(nr, nc)] = nd
                    dq.appendleft((nd, (nr, nc))) if cost == 0 else dq.append((nd, (nr, nc)))
        return dist

    if color == "R":
        fwd = bfs([(0, c)       for c in range(dim_y)])
        bwd = bfs([(dim_x-1, c) for c in range(dim_y)])
    else:
        fwd = bfs([(r, 0)       for r in range(dim_x)])
        bwd = bfs([(r, dim_y-1) for r in range(dim_x)])

    blocked = {pos for pos, d in fwd.items()
               if not env.get(pos) and d + bwd.get(pos, INF) - 1 == d1}
    if not blocked:
        return INF

    tmp = dict(env)
    for pos in blocked:
        tmp[pos] = _FakePiece("X")
    return _shortest_path(tmp, dim_x, dim_y, color)


def _has_won(env: dict, dim_x: int, dim_y: int, color: str) -> bool:
    """Flood-fill win detection."""
    if color == "R":
        starts = [(0, c) for c in range(dim_y)
                  if env.get((0, c)) and env[(0, c)].piece_type == color]
        goal = lambda r, c: r == dim_x - 1
    else:
        starts = [(r, 0) for r in range(dim_x)
                  if env.get((r, 0)) and env[(r, 0)].piece_type == color]
        goal = lambda r, c: c == dim_y - 1

    visited = set()
    stack   = list(starts)
    while stack:
        r, c = stack.pop()
        if (r, c) in visited:
            continue
        visited.add((r, c))
        if goal(r, c):
            return True
        for dr, dc in HEX_DIRS:
            nr, nc = r + dr, c + dc
            if (_in_bounds(nr, nc, dim_x, dim_y)
                    and (nr, nc) not in visited
                    and env.get((nr, nc))
                    and env[(nr, nc)].piece_type == color):
                stack.append((nr, nc))
    return False


def _is_strong_opening(pos: tuple, dim_x: int, dim_y: int) -> bool:
    r, c   = pos
    margin = min(dim_x, dim_y) // 3
    return (margin <= r <= dim_x - 1 - margin and
            margin <= c <= dim_y - 1 - margin)


# ======================================================================
# Yang et al. knowledge structures
# ======================================================================

class ConnectedString:
    """
    A maximal connected group of same-color stones.
    string_type encodes which borders the string touches (ST_TOP / ST_BOTTOM).
    """
    __slots__ = ("cells", "string_type", "color")

    def __init__(self, cells: frozenset, string_type: int, color: str):
        self.cells       = cells
        self.string_type = string_type
        self.color       = color

    def touches_source(self) -> bool:
        return bool(self.string_type & ST_TOP)

    def touches_target(self) -> bool:
        return bool(self.string_type & ST_BOTTOM)

    def is_winning(self) -> bool:
        return (self.string_type & ST_TOPBOTTOM) == ST_TOPBOTTOM


class VirtualConnection:
    """
    A pattern-matched virtual connection between two ConnectedStrings.
    The carrier is the set of empty cells forming the connection template.
    If the opponent plays inside the carrier, the connection is broken.
    """
    __slots__ = ("s1", "s2", "carrier")

    def __init__(self, s1: ConnectedString, s2: ConnectedString,
                 carrier: frozenset):
        self.s1      = s1
        self.s2      = s2
        self.carrier = carrier


class Group:
    """
    A cluster of ConnectedStrings linked by VirtualConnections.
    group_type is the union of all member string_types.
    """
    __slots__ = ("strings", "group_type", "vcs", "color")

    def __init__(self, strings: list, group_type: int,
                 vcs: list, color: str):
        self.strings    = strings
        self.group_type = group_type
        self.vcs        = vcs
        self.color      = color

    def touches_source(self) -> bool:
        return bool(self.group_type & ST_TOP)

    def touches_target(self) -> bool:
        return bool(self.group_type & ST_BOTTOM)

    def is_winning(self) -> bool:
        return (self.group_type & ST_TOPBOTTOM) == ST_TOPBOTTOM

    def all_cells(self) -> set:
        cells = set()
        for s in self.strings:
            cells |= s.cells
        return cells

    def carrier(self) -> set:
        c = set()
        for vc in self.vcs:
            c |= vc.carrier
        return c

    def vc_count(self) -> int:
        return len(self.vcs)


# ======================================================================
# Virtual connection pattern detection
# ======================================================================

def _find_virtual_connections(env: dict, dim_x: int, dim_y: int,
                               strings: list, color: str) -> list:
    """
    Finds all virtual connections between pairs of ConnectedStrings.

    Pattern 1 — Bridge (Figure 10 of the paper):
      Stones A and B where B = A + d1 + d2 for two hex directions d1, d2.
      Carrier = {A+d1, A+d2}  (both must be empty).

    Pattern 2 — Ziggurat (Figure 11 of the paper):
      Stones A and B where B = A + 2*d1 + d2.
      Carrier = {A+d1, A+2*d1, A+d1+d2}  (all three must be empty).

    Each pattern is checked for all direction pairs (6 rotations implicit).
    """
    vcs = []

    cell_to_string = {}
    for s in strings:
        for cell in s.cells:
            cell_to_string[cell] = s

    def is_empty(pos):
        return _in_bounds(*pos, dim_x, dim_y) and pos not in env

    def is_own(pos):
        return (_in_bounds(*pos, dim_x, dim_y)
                and env.get(pos)
                and env[pos].piece_type == color)

    seen = set()

    # Pattern 1: Bridge
    for i, (dr1, dc1) in enumerate(HEX_DIRS):
        for dr2, dc2 in HEX_DIRS[i+1:]:
            for s1 in strings:
                for (ar, ac) in s1.cells:
                    c1 = (ar + dr1, ac + dc1)
                    c2 = (ar + dr2, ac + dc2)
                    if not is_empty(c1) or not is_empty(c2):
                        continue
                    b  = (ar + dr1 + dr2, ac + dc1 + dc2)
                    if not is_own(b):
                        continue
                    s2 = cell_to_string.get(b)
                    if s2 is None or s2 is s1:
                        continue
                    key = (id(s1), id(s2), frozenset([c1, c2]))
                    if key not in seen:
                        seen.add(key)
                        vcs.append(VirtualConnection(
                            s1, s2, frozenset([c1, c2])))

    # Pattern 2: Ziggurat
    for dr1, dc1 in HEX_DIRS:
        for dr2, dc2 in HEX_DIRS:
            if (dr1, dc1) == (dr2, dc2):
                continue
            for s1 in strings:
                for (ar, ac) in s1.cells:
                    m1 = (ar + dr1,         ac + dc1)
                    m2 = (ar + 2*dr1,       ac + 2*dc1)
                    m3 = (ar + dr1 + dr2,   ac + dc1 + dc2)
                    b  = (ar + 2*dr1 + dr2, ac + 2*dc1 + dc2)
                    if not all(is_empty(p) for p in [m1, m2, m3]):
                        continue
                    if not is_own(b):
                        continue
                    s2 = cell_to_string.get(b)
                    if s2 is None or s2 is s1:
                        continue
                    carrier = frozenset([m1, m2, m3])
                    key = (id(s1), id(s2), carrier)
                    if key not in seen:
                        seen.add(key)
                        vcs.append(VirtualConnection(s1, s2, carrier))

    return vcs


# ======================================================================
# Group builder (Union-Find over strings via VCs)
# ======================================================================

def _build_groups(env: dict, dim_x: int, dim_y: int,
                   color: str) -> list:
    """
    1. Find all ConnectedStrings.
    2. Add virtual border strings (the board edges themselves).
    3. Find all VirtualConnections.
    4. Merge into Groups using Union-Find.
    """
    # Step 1: connected strings
    visited = set()
    strings = []

    for r in range(dim_x):
        for c in range(dim_y):
            if (r, c) in visited:
                continue
            p = env.get((r, c))
            if not p or p.piece_type != color:
                continue
            cells = set()
            stype = ST_NONE
            stack = [(r, c)]
            while stack:
                cr, cc = stack.pop()
                if (cr, cc) in cells:
                    continue
                cells.add((cr, cc))
                visited.add((cr, cc))
                if color == "R":
                    if cr == 0:         stype |= ST_TOP
                    if cr == dim_x - 1: stype |= ST_BOTTOM
                else:
                    if cc == 0:         stype |= ST_TOP
                    if cc == dim_y - 1: stype |= ST_BOTTOM
                for dr, dc in HEX_DIRS:
                    nr, nc = cr + dr, cc + dc
                    if (_in_bounds(nr, nc, dim_x, dim_y)
                            and (nr, nc) not in cells
                            and env.get((nr, nc))
                            and env[(nr, nc)].piece_type == color):
                        stack.append((nr, nc))
            strings.append(ConnectedString(frozenset(cells), stype, color))

    # Step 2: virtual border strings (empty cells on the edges)
    if color == "R":
        top_cells = frozenset((0, c)       for c in range(dim_y) if not env.get((0, c)))
        bot_cells = frozenset((dim_x-1, c) for c in range(dim_y) if not env.get((dim_x-1, c)))
    else:
        top_cells = frozenset((r, 0)       for r in range(dim_x) if not env.get((r, 0)))
        bot_cells = frozenset((r, dim_y-1) for r in range(dim_x) if not env.get((r, dim_y-1)))

    v_top = ConnectedString(top_cells, ST_TOP,    color)
    v_bot = ConnectedString(bot_cells, ST_BOTTOM, color)
    all_strings = strings + [v_top, v_bot]

    # Step 3: virtual connections
    vcs = _find_virtual_connections(env, dim_x, dim_y, all_strings, color)

    # Step 4: Union-Find merge
    parent = {id(s): s for s in all_strings}

    def find(s):
        while id(parent[id(s)]) != id(s):
            parent[id(s)] = parent[id(parent[id(s)])]
            s = parent[id(s)]
        return s

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra is not rb:
            parent[id(rb)] = ra

    for vc in vcs:
        union(vc.s1, vc.s2)

    root_to_members = {}
    for s in all_strings:
        root = find(s)
        root_to_members.setdefault(id(root), []).append(s)

    groups = []
    for members in root_to_members.values():
        gtype     = ST_NONE
        group_vcs = []
        root      = find(members[0])
        for s in members:
            gtype |= s.string_type
        for vc in vcs:
            if find(vc.s1) is root and find(vc.s2) is root:
                group_vcs.append(vc)
        groups.append(Group(members, gtype, group_vcs, color))

    return groups


# ======================================================================
# OneToConnect and OnePossibleConnect move generation helpers
# ======================================================================

def _one_to_connect_moves(group: Group, env: dict,
                           dim_x: int, dim_y: int,
                           target_type: int) -> set:
    """
    Empty cells that, if played, would directly extend `group` to
    touch border `target_type`, OR are carrier cells of a VC that
    links to a string already touching `target_type`.
    """
    moves = set()

    for (r, c) in group.all_cells():
        for dr, dc in HEX_DIRS:
            nr, nc = r + dr, c + dc
            if not _in_bounds(nr, nc, dim_x, dim_y):
                continue
            pos = (nr, nc)
            if env.get(pos):
                continue
            if group.color == "R":
                touches = ((target_type == ST_TOP    and nr == 0) or
                           (target_type == ST_BOTTOM and nr == dim_x - 1))
            else:
                touches = ((target_type == ST_TOP    and nc == 0) or
                           (target_type == ST_BOTTOM and nc == dim_y - 1))
            if touches:
                moves.add(pos)

    for vc in group.vcs:
        other = vc.s2 if vc.s1 in group.strings else vc.s1
        if other.string_type & target_type:
            moves |= set(vc.carrier)

    return moves


def _one_possible_connect_moves(group: Group, env: dict,
                                 dim_x: int, dim_y: int,
                                 target_type: int) -> set:
    """
    Empty cells adjacent to the group that are directionally toward
    `target_type` — "OnePossibleConnect" moves from the paper.
    """
    moves      = set()
    group_cells = group.all_cells()
    if not group_cells:
        return moves

    if group.color == "R":
        avg = sum(r for r, c in group_cells) / len(group_cells)
    else:
        avg = sum(c for r, c in group_cells) / len(group_cells)

    for (r, c) in group_cells:
        for dr, dc in HEX_DIRS:
            nr, nc = r + dr, c + dc
            if not _in_bounds(nr, nc, dim_x, dim_y):
                continue
            pos = (nr, nc)
            if env.get(pos):
                continue
            if group.color == "R":
                coord = nr
            else:
                coord = nc
            if target_type == ST_BOTTOM and coord >= avg:
                moves.add(pos)
            elif target_type == ST_TOP and coord <= avg:
                moves.add(pos)

    return moves


# ======================================================================
# 13 move-generation rules (Section 4 — Yang et al.)
# ======================================================================

def _generate_candidates(env: dict, dim_x: int, dim_y: int,
                          my_color: str, opp_color: str) -> list:
    """
    Apply all 13 rules in priority order.
    Returns a list of positions sorted by priority (lower = more urgent).
    Falls back to centre-distance ordering if no rules fire.
    """
    my_groups  = _build_groups(env, dim_x, dim_y, my_color)
    opp_groups = _build_groups(env, dim_x, dim_y, opp_color)

    scored = {}   # pos -> best priority (lower = more important)

    def add(pos, priority):
        if pos not in env:
            if pos not in scored or priority < scored[pos]:
                scored[pos] = priority

    # ── Rules 1 & 2: Immediate win / block ────────────────────────────
    for g in my_groups:
        if g.is_winning():
            for pos in g.carrier():
                add(pos, 1)

    for g in opp_groups:
        if g.is_winning():
            for pos in g.carrier():
                add(pos, 2)

    # ── Rules 3 & 4: OneToConnect from border groups ──────────────────
    for g in my_groups:
        if g.touches_source() and not g.touches_target():
            for pos in _one_to_connect_moves(g, env, dim_x, dim_y, ST_BOTTOM):
                add(pos, 3)

    for g in my_groups:
        if g.touches_target() and not g.touches_source():
            for pos in _one_to_connect_moves(g, env, dim_x, dim_y, ST_TOP):
                add(pos, 4)

    # ── Rules 5 & 6: OneToConnect chaining through mid group ──────────
    for g1 in my_groups:
        if not g1.touches_source():
            continue
        for g2 in my_groups:
            if g2 is g1 or not g2.touches_target():
                continue
            otc1 = _one_to_connect_moves(g1, env, dim_x, dim_y, ST_BOTTOM)
            otc2 = _one_to_connect_moves(g2, env, dim_x, dim_y, ST_TOP)
            for pos in otc1 | otc2:
                add(pos, 5)

    for g1 in my_groups:
        if not g1.touches_target():
            continue
        for g2 in my_groups:
            if g2 is g1 or not g2.touches_source():
                continue
            otc1 = _one_to_connect_moves(g1, env, dim_x, dim_y, ST_TOP)
            otc2 = _one_to_connect_moves(g2, env, dim_x, dim_y, ST_BOTTOM)
            for pos in otc1 | otc2:
                add(pos, 6)

    # ── Rules 7 & 8: OnePossibleConnect from border groups ────────────
    for g in my_groups:
        if g.touches_source() and not g.touches_target():
            for pos in _one_possible_connect_moves(g, env, dim_x, dim_y, ST_BOTTOM):
                add(pos, 7)

    for g in my_groups:
        if g.touches_target() and not g.touches_source():
            for pos in _one_possible_connect_moves(g, env, dim_x, dim_y, ST_TOP):
                add(pos, 8)

    # ── Rules 9 & 10: OnePossibleConnect chaining ─────────────────────
    for g1 in my_groups:
        if not g1.touches_source():
            continue
        for g2 in my_groups:
            if g2 is g1 or not g2.touches_target():
                continue
            opc1 = _one_possible_connect_moves(g1, env, dim_x, dim_y, ST_BOTTOM)
            opc2 = _one_possible_connect_moves(g2, env, dim_x, dim_y, ST_TOP)
            for pos in opc1 | opc2:
                add(pos, 9)

    for g1 in my_groups:
        if not g1.touches_target():
            continue
        for g2 in my_groups:
            if g2 is g1 or not g2.touches_source():
                continue
            opc1 = _one_possible_connect_moves(g1, env, dim_x, dim_y, ST_TOP)
            opc2 = _one_possible_connect_moves(g2, env, dim_x, dim_y, ST_BOTTOM)
            for pos in opc1 | opc2:
                add(pos, 10)

    # ── Rules 11–13: Groups with OTC moves to both borders ────────────
    # Rule 11: Single group has OTC to both Top and Bottom
    for g in my_groups:
        to_top = _one_to_connect_moves(g, env, dim_x, dim_y, ST_TOP)
        to_bot = _one_to_connect_moves(g, env, dim_x, dim_y, ST_BOTTOM)
        if to_top and to_bot:
            p_top = 11 if len(to_top) <= len(to_bot) else 12
            p_bot = 11 if len(to_bot) <= len(to_top) else 12
            for pos in to_top: add(pos, p_top)
            for pos in to_bot: add(pos, p_bot)

    # Rule 12: Top group → OTC to mid group → OTC to Bottom
    for g1 in my_groups:
        if not g1.touches_source():
            continue
        for g2 in my_groups:
            if g2 is g1:
                continue
            for g3 in my_groups:
                if g3 is g1 or g3 is g2 or not g3.touches_target():
                    continue
                otc_12 = _one_to_connect_moves(g1, env, dim_x, dim_y, ST_BOTTOM)
                otc_23 = _one_to_connect_moves(g2, env, dim_x, dim_y, ST_TOP)
                if otc_12 and otc_23:
                    pa = 12 if len(otc_12) <= len(otc_23) else 13
                    pb = 12 if len(otc_23) <= len(otc_12) else 13
                    for pos in otc_12: add(pos, pa)
                    for pos in otc_23: add(pos, pb)

    # Rule 13: Bottom group → OTC to mid → OTC to Top (symmetric)
    for g1 in my_groups:
        if not g1.touches_target():
            continue
        for g2 in my_groups:
            if g2 is g1:
                continue
            for g3 in my_groups:
                if g3 is g1 or g3 is g2 or not g3.touches_source():
                    continue
                otc_12 = _one_to_connect_moves(g1, env, dim_x, dim_y, ST_TOP)
                otc_23 = _one_to_connect_moves(g2, env, dim_x, dim_y, ST_BOTTOM)
                if otc_12 and otc_23:
                    pa = 12 if len(otc_12) <= len(otc_23) else 13
                    pb = 12 if len(otc_23) <= len(otc_12) else 13
                    for pos in otc_12: add(pos, pa)
                    for pos in otc_23: add(pos, pb)

    if not scored:
        # Fallback: centre-distance ordering
        cx, cy = dim_x / 2, dim_y / 2
        empties = [(r, c) for r in range(dim_x) for c in range(dim_y)
                   if (r, c) not in env]
        return sorted(empties, key=lambda p: abs(p[0]-cx) + abs(p[1]-cy))

    return [pos for pos, _ in sorted(scored.items(), key=lambda x: x[1])]


# ======================================================================
# Evaluation function (no ML — hand-crafted from paper concepts)
# ======================================================================

def _evaluate(env: dict, dim_x: int, dim_y: int,
               my_color: str, opp_color: str,
               my_groups: list, opp_groups: list) -> float:
    """
    Score = opp_d1 - my_d1                     (primary path, weight 1.0)
          + 0.5 * (opp_d2 - my_d2)             (two-distance bonus)
          + 0.3 * vc_advantage                  (virtual connection count)
          + 0.2 * border_group_advantage        (groups touching borders)

    All terms are from or directly motivated by Yang et al.:
    - d1/d2: shortest / second-shortest path (carrier/influence region size)
    - VC advantage: more VCs = more resilient connections
    - Border group advantage: groups already anchored to an edge
    """
    INF = math.inf

    # ── d1 ──────────────────────────────────────────────────────────
    my_d1  = _shortest_path(env, dim_x, dim_y, my_color)
    opp_d1 = _shortest_path(env, dim_x, dim_y, opp_color)

    if opp_d1 == INF and my_d1 == INF:
        return 0.0
    if opp_d1 == INF:
        return  1_000_000.0
    if my_d1 == INF:
        return -1_000_000.0

    d1_score = opp_d1 - my_d1

    # ── d2 ──────────────────────────────────────────────────────────
    my_d2  = _second_shortest_path(env, dim_x, dim_y, my_color,  my_d1)
    opp_d2 = _second_shortest_path(env, dim_x, dim_y, opp_color, opp_d1)
    my_d2_v  = my_d2  if my_d2  < INF else my_d1  * 3
    opp_d2_v = opp_d2 if opp_d2 < INF else opp_d1 * 3
    d2_score = opp_d2_v - my_d2_v

    # ── Virtual connection advantage ─────────────────────────────────
    # More VCs in a group = more robust connections (harder to block)
    my_vc_count  = sum(g.vc_count() for g in my_groups)
    opp_vc_count = sum(g.vc_count() for g in opp_groups)
    vc_score = (my_vc_count - opp_vc_count) / max(1, my_vc_count + opp_vc_count)

    # ── Border group advantage ───────────────────────────────────────
    # Groups touching one border are closer to winning
    my_border  = sum(1 for g in my_groups
                     if g.touches_source() or g.touches_target())
    opp_border = sum(1 for g in opp_groups
                     if g.touches_source() or g.touches_target())
    border_score = (my_border - opp_border) / max(1, my_border + opp_border)

    return (1.0 * d1_score
            + 0.5 * d2_score
            + 0.3 * vc_score
            + 0.2 * border_score)


# ======================================================================
# Agent
# ======================================================================

class MyPlayer(PlayerHex):
    """
    Minimax + alpha-beta pruning with Yang et al. heuristics.
    No machine learning — all weights are hand-crafted from the paper.

    piece_type "R": row 0 -> row dim_x-1  (top to bottom)
    piece_type "B": col 0 -> col dim_y-1  (left to right)
    """

    MAX_DEPTH  = 6    # ceiling — iterative deepening stops at time limit
    MAX_MOVES  = 15   # candidates per node
    TIME_LIMIT = 15.0 # hard cap per move (seconds)

    def __init__(self, piece_type: str, name: str = "MyPlayer"):
        super().__init__(piece_type, name)
        self._start_time = 0.0
        self._time_limit = self.TIME_LIMIT
        self._tt         = {}

    def _out_of_time(self) -> bool:
        return time.time() - self._start_time >= self._time_limit

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def compute_action(self, current_state: GameState,
                       remaining_time: int = 1e9, **kwargs) -> Action:
        self._start_time = time.time()
        self._tt.clear()

        env   = current_state.rep.env
        dim_x = current_state.rep.dimensions[0]
        dim_y = current_state.rep.dimensions[1]

        # Dynamic time budget
        moves_played     = len(env)
        moves_left       = max(10, 50 - moves_played)
        dynamic_limit    = (remaining_time * 0.85) / moves_left
        self._time_limit = min(dynamic_limit, self.TIME_LIMIT)

        # Always return a framework-valid action
        possible_actions = list(current_state.get_possible_stateless_actions())
        pos_to_action    = {a.data["position"]: a for a in possible_actions}

        def pick(pos):
            return pos_to_action.get(pos, possible_actions[0])

        # Pie rule
        if self.piece_type == "R" and len(env) == 0:
            return pick((1, 1))
        if self.piece_type == "B" and len(env) == 1:
            opp_pos = list(env.keys())[0]
            if _is_strong_opening(opp_pos, dim_x, dim_y):
                return pick(opp_pos)

        opponent = "B" if self.piece_type == "R" else "R"

        # Yang et al. 13-rule candidate generation
        candidates = _generate_candidates(
            env, dim_x, dim_y, self.piece_type, opponent
        )[:self.MAX_MOVES]

        if not candidates:
            return possible_actions[0]

        # Iterative deepening
        best_pos = candidates[0]
        for depth in range(1, self.MAX_DEPTH + 1):
            if self._out_of_time():
                break
            result = self._search_root(
                candidates, env, dim_x, dim_y,
                depth, self.piece_type, opponent)
            if result is not None:
                best_pos = result

        return pick(best_pos)

    # ------------------------------------------------------------------
    # Root search at fixed depth
    # ------------------------------------------------------------------

    def _search_root(self, candidates, env, dim_x, dim_y,
                     depth, my_color, opp_color):
        best_score = -math.inf
        best_pos   = None

        for pos in candidates:
            if self._out_of_time():
                return None   # incomplete depth — discard

            new_env = dict(env)
            new_env[pos] = _FakePiece(my_color)

            score = self._minimax(
                new_env, dim_x, dim_y, depth - 1,
                -math.inf, math.inf, False, my_color, opp_color)

            if score > best_score:
                best_score = score
                best_pos   = pos

        return best_pos

    # ------------------------------------------------------------------
    # Minimax + alpha-beta + transposition table
    # ------------------------------------------------------------------

    def _minimax(self, env, dim_x, dim_y, depth, alpha, beta,
                 is_maximising, my_color, opp_color):

        if _has_won(env, dim_x, dim_y, my_color):
            return  1_000_000
        if _has_won(env, dim_x, dim_y, opp_color):
            return -1_000_000

        empty = [(r, c) for r in range(dim_x) for c in range(dim_y)
                 if (r, c) not in env]

        if depth == 0 or not empty or self._out_of_time():
            # Build groups once and pass to evaluator
            my_g  = _build_groups(env, dim_x, dim_y, my_color)
            opp_g = _build_groups(env, dim_x, dim_y, opp_color)
            return _evaluate(env, dim_x, dim_y, my_color, opp_color,
                              my_g, opp_g)

        # Transposition table
        tt_key = (tuple(sorted(
            (pos, piece.piece_type) for pos, piece in env.items()
        )), depth, is_maximising)
        if tt_key in self._tt:
            return self._tt[tt_key]

        # Yang et al. candidate generation at inner nodes too
        color = my_color if is_maximising else opp_color
        opp   = opp_color if is_maximising else my_color
        candidates = _generate_candidates(
            env, dim_x, dim_y, color, opp
        )[:self.MAX_MOVES]

        if not candidates:
            cx, cy = dim_x / 2, dim_y / 2
            candidates = sorted(empty,
                key=lambda p: abs(p[0]-cx)+abs(p[1]-cy))[:self.MAX_MOVES]

        if is_maximising:
            value = -math.inf
            for pos in candidates:
                new_env = dict(env)
                new_env[pos] = _FakePiece(color)
                value = max(value, self._minimax(
                    new_env, dim_x, dim_y, depth - 1,
                    alpha, beta, False, my_color, opp_color))
                alpha = max(alpha, value)
                if alpha >= beta:
                    break
        else:
            value = math.inf
            for pos in candidates:
                new_env = dict(env)
                new_env[pos] = _FakePiece(color)
                value = min(value, self._minimax(
                    new_env, dim_x, dim_y, depth - 1,
                    alpha, beta, True, my_color, opp_color))
                beta = min(beta, value)
                if alpha >= beta:
                    break

        self._tt[tt_key] = value
        return value
