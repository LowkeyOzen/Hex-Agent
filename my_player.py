import math
import time
from collections import deque
from player_hex import PlayerHex
from seahorse.game.action import Action
from seahorse.game.game_state import GameState
from seahorse.game.stateless_action import StatelessAction

# Hex Agent — Minimax + Alpha-Beta + Transposition Table + Bridge Heuristic
# With alpha-beta pruning.
#
# The bridge pattern (Figure 10, Yang et al.):
#   Two stones A and B where B = A + d1 + d2 for two hex directions.
#   The two intermediate cells form the carrier.
#   A bridge is a guaranteed virtual connection — if the opponent plays
#   one carrier cell, you play the other and the connection holds.
#
# Heuristic:
#   score = (opp_d1 - my_d1)              primary path advantage
#         + 0.5 * (opp_bridges - my_bridges)  bridge count advantage


HEX_DIRS = [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)]


# ======================================================================
# Helpers
# ======================================================================

class _FakePiece:
    __slots__ = ("piece_type",)
    def __init__(self, piece_type: str):
        self.piece_type = piece_type


def _in_bounds(r, c, dim_x, dim_y) -> bool:
    return 0 <= r < dim_x and 0 <= c < dim_y


def _shortest_path(env: dict, dim_x: int, dim_y: int, color: str) -> float:
    """0-1 BFS. Own stone = 0, empty = 1, opponent = blocked."""
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


def _count_bridges(env: dict, dim_x: int, dim_y: int, color: str) -> int:
    """
    Count the number of bridge patterns for `color`.

    A bridge exists between stones A and B when:
      - B = A + d1 + d2  for two distinct hex directions d1, d2
      - Both intermediate cells (A+d1) and (A+d2) are empty

    The two empty cells form the carrier. As long as both are empty,
    the connection is guaranteed regardless of opponent play.

    We count unique bridges (each pair counted once).
    """
    count = 0
    seen  = set()

    for r in range(dim_x):
        for c in range(dim_y):
            p = env.get((r, c))
            if not p or p.piece_type != color:
                continue
            # Try all pairs of directions
            for i, (dr1, dc1) in enumerate(HEX_DIRS):
                for dr2, dc2 in HEX_DIRS[i+1:]:
                    c1 = (r + dr1, c + dc1)   # carrier cell 1
                    c2 = (r + dr2, c + dc2)   # carrier cell 2
                    b  = (r + dr1 + dr2, c + dc1 + dc2)  # bridge target

                    if not _in_bounds(*c1, dim_x, dim_y): continue
                    if not _in_bounds(*c2, dim_x, dim_y): continue
                    if not _in_bounds(*b,  dim_x, dim_y): continue

                    # Both carrier cells must be empty
                    if env.get(c1) or env.get(c2):
                        continue

                    # Target must be own stone
                    pb = env.get(b)
                    if not pb or pb.piece_type != color:
                        continue

                    # Deduplicate: count each bridge once
                    key = (min((r,c), b), max((r,c), b))
                    if key not in seen:
                        seen.add(key)
                        count += 1

    return count


def _has_won(env: dict, dim_x: int, dim_y: int, color: str) -> bool:
    """Flood-fill win check."""
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


def _is_strong_opening(pos, dim_x, dim_y) -> bool:
    r, c   = pos
    margin = min(dim_x, dim_y) // 3
    return (margin <= r <= dim_x - 1 - margin and
            margin <= c <= dim_y - 1 - margin)


def _order_moves(moves, dim_x, dim_y) -> list:
    """Centre-distance ordering for inner nodes — fast, no BFS needed."""
    cx, cy = dim_x / 2, dim_y / 2
    return sorted(moves, key=lambda p: abs(p[0]-cx) + abs(p[1]-cy))


def _order_moves_by_gain(moves, env, dim_x, dim_y,
                          my_color, opp_color) -> list:
    """
    Root-level ordering: score each move by path gain for both players.
    Moves that shorten our path OR lengthen opponent's path come first.
    This gives alpha-beta the best moves to explore first, maximising cuts.
    Called only once at the root — inner nodes use fast centre-distance.
    """
    base_my  = _shortest_path(env, dim_x, dim_y, my_color)
    base_opp = _shortest_path(env, dim_x, dim_y, opp_color)

    def gain(pos):
        e = dict(env)
        e[pos] = _FakePiece(my_color)
        our  = base_my  - _shortest_path(e, dim_x, dim_y, my_color)   # positive = we improve
        e[pos] = _FakePiece(opp_color)
        theirs = base_opp - _shortest_path(e, dim_x, dim_y, opp_color) # positive = they improve
        return our + theirs   # high = important for both sides

    return sorted(moves, key=gain, reverse=True)


# ======================================================================
# Agent
# ======================================================================

class MyPlayer(PlayerHex):
    """
    Minimax with alpha-beta pruning, transposition table and bridge heuristic.

    piece_type "R": row 0 -> row dim_x-1  (top to bottom)
    piece_type "B": col 0 -> col dim_y-1  (left to right)
    """

    MAX_DEPTH  = 3    # can go deeper now that alpha-beta prunes the tree
    MAX_MOVES  = 30   # more candidates — alpha-beta handles the cost
    TIME_LIMIT = 25.0 # hard cap per move (seconds)

    # Bridge weight in the heuristic
    BRIDGE_WEIGHT = 0.5

    def __init__(self, piece_type: str, name: str = "MyPlayer"):
        super().__init__(piece_type, name)
        self._start_time = 0.0
        self._time_limit = self.TIME_LIMIT
        self._tt         = {}   # transposition table: board_key -> score

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

        # Order candidates by path gain (heuristic-aware) at root
        # Inner minimax nodes use cheap centre-distance ordering
        empty      = list(current_state.rep.get_empty())
        candidates = _order_moves_by_gain(
            empty, env, dim_x, dim_y, self.piece_type, opponent
        )[:self.MAX_MOVES]

        if not candidates:
            return possible_actions[0]

        # Pick the best move
        best_score = -math.inf
        best_pos   = candidates[0]

        for pos in candidates:
            if self._out_of_time():
                break
            new_env = dict(env)
            new_env[pos] = _FakePiece(self.piece_type)
            score = self._minimax(
                new_env, dim_x, dim_y,
                depth         = self.MAX_DEPTH - 1,
                is_maximising = False,
                my_color      = self.piece_type,
                opp_color     = opponent,
                alpha         = -math.inf,
                beta          =  math.inf,
            )
            if score > best_score:
                best_score = score
                best_pos   = pos

        return pick(best_pos)

    # ------------------------------------------------------------------
    # Minimax with alpha-beta pruning + transposition table
    # ------------------------------------------------------------------

    def _minimax(self, env: dict, dim_x: int, dim_y: int,
                 depth: int, is_maximising: bool,
                 my_color: str, opp_color: str,
                 alpha: float = -math.inf,
                 beta:  float =  math.inf) -> float:

        # Terminal: win/loss
        if _has_won(env, dim_x, dim_y, my_color):
            return  1_000_000.0
        if _has_won(env, dim_x, dim_y, opp_color):
            return -1_000_000.0

        empty = [(r, c) for r in range(dim_x) for c in range(dim_y)
                 if (r, c) not in env]

        if depth == 0 or not empty or self._out_of_time():
            return self._heuristic(env, dim_x, dim_y, my_color, opp_color)

        # Transposition table lookup (with bound flags)
        # EXACT=0: true minimax value
        # LOWER=1: value is a lower bound (alpha cut occurred below)
        # UPPER=2: value is an upper bound (beta cut occurred below)
        tt_key = (
            tuple(sorted((pos, p.piece_type) for pos, p in env.items())),
            depth,
            is_maximising,
        )
        if tt_key in self._tt:
            tt_val, tt_flag = self._tt[tt_key]
            if tt_flag == 0:                  # exact — use directly
                return tt_val
            elif tt_flag == 1 and tt_val >= beta:   # lower bound — still causes β-cut
                return tt_val
            elif tt_flag == 2 and tt_val <= alpha:  # upper bound — still causes α-cut
                return tt_val

        # Move ordering + cap
        candidates = _order_moves(empty, dim_x, dim_y)[:self.MAX_MOVES]
        color      = my_color if is_maximising else opp_color

        if is_maximising:
            value = -math.inf
            for pos in candidates:
                new_env = dict(env)
                new_env[pos] = _FakePiece(color)
                value = max(value, self._minimax(
                    new_env, dim_x, dim_y, depth - 1,
                    False, my_color, opp_color, alpha, beta))
                alpha = max(alpha, value)
                if alpha >= beta:
                    break  # β-cut: maximiser already has better option above
        else:
            value = math.inf
            for pos in candidates:
                new_env = dict(env)
                new_env[pos] = _FakePiece(color)
                value = min(value, self._minimax(
                    new_env, dim_x, dim_y, depth - 1,
                    True, my_color, opp_color, alpha, beta))
                beta = min(beta, value)
                if alpha >= beta:
                    break  # α-cut: minimiser already has better option above

        # Store with flag: exact if no cut, lower/upper if cut occurred
        if value <= alpha:
            self._tt[tt_key] = (value, 2)   # upper bound (β pruned children)
        elif value >= beta:
            self._tt[tt_key] = (value, 1)   # lower bound (α pruned children)
        else:
            self._tt[tt_key] = (value, 0)   # exact value
        return value

    # ------------------------------------------------------------------
    # Heuristic: shortest path + bridge count
    # ------------------------------------------------------------------

    def _heuristic(self, env: dict, dim_x: int, dim_y: int,
                   my_color: str, opp_color: str) -> float:
        """
        score = (opp_d1 - my_d1)
              + BRIDGE_WEIGHT * (my_bridges - opp_bridges)

        - opp_d1 - my_d1: positive means we are closer to winning.
        - my_bridges - opp_bridges: more bridges = more secure connections.
          A bridge is guaranteed regardless of opponent play (Yang et al.).
        """
        INF = math.inf

        my_d1  = _shortest_path(env, dim_x, dim_y, my_color)
        opp_d1 = _shortest_path(env, dim_x, dim_y, opp_color)

        if opp_d1 == INF and my_d1 == INF:
            return 0.0
        if opp_d1 == INF:
            return  1_000_000.0
        if my_d1 == INF:
            return -1_000_000.0

        my_bridges  = _count_bridges(env, dim_x, dim_y, my_color)
        opp_bridges = _count_bridges(env, dim_x, dim_y, opp_color)

        # Normalize bridge bonus to same scale as path difference.
        # Path diff is in [-(dim-1), +(dim-1)].
        # Bridge diff can be much larger — cap its influence to 1.0
        # so it acts as a tiebreaker, not the primary signal.
        path_diff   = opp_d1 - my_d1
        bridge_diff = my_bridges - opp_bridges
        max_bridges = max(1, my_bridges + opp_bridges)
        bridge_norm = bridge_diff / max_bridges  # normalised to [-1, +1]

        return path_diff + self.BRIDGE_WEIGHT * bridge_norm
