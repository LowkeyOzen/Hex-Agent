import math
import heapq
import time
from player_hex import PlayerHex
from seahorse.game.action import Action
from seahorse.game.game_state import GameState
from seahorse.game.stateless_action import StatelessAction

# Upgraded Hex Agent — Minimax + Alpha-Beta + Shortest-Path Heuristic

class MyPlayer(PlayerHex):
    """
    Hex agent using minimax with alpha-beta pruning.
    Heuristic: difference of shortest connecting path lengths (Dijkstra).

    piece_type: "R" connects top-to-bottom (row 0 → row x-1)
                "B" connects left-to-right (col 0 → col y-1)
    """

    MAX_DEPTH  = 2    # Depth 3 is too slow on 14×14 — use 2, rely on good move ordering
    MAX_MOVES  = 15   # More candidates on a bigger board, still fast enough
    TIME_LIMIT = 4.0  # Seconds — stay well under seahorse's timeout

    def __init__(self, piece_type: str, name: str = "MyPlayer"):
        super().__init__(piece_type, name)
        self._start_time = 0.0

    def _out_of_time(self) -> bool:
        return time.time() - self._start_time >= self.TIME_LIMIT

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def compute_action(self, current_state: GameState, remaining_time: int = 1e9, **kwargs) -> Action:
        self._start_time = time.time()

        env   = current_state.rep.env
        dim_x = current_state.rep.dimensions[0]
        dim_y = current_state.rep.dimensions[1]

        # Opening: play the centre
        if len(env) == 0:
            cx, cy = dim_x // 2, dim_y // 2
            return StatelessAction({"piece": self.piece_type, "position": (cx, cy)})

        opponent = "B" if self.piece_type == "R" else "R"
        empty    = list(current_state.rep.get_empty())

        # Order by heuristic at root (smarter), cap to MAX_MOVES
        empty = self._order_moves_by_heuristic(empty, env, dim_x, dim_y, self.piece_type, opponent)[:self.MAX_MOVES]

        best_score = -math.inf
        best_pos   = empty[0]

        for pos in empty:
            if self._out_of_time():
                break

            new_env = dict(env)
            new_env[pos] = _FakePiece(self.piece_type)

            score = self._minimax(
                new_env, dim_x, dim_y,
                depth=self.MAX_DEPTH - 1,
                alpha=-math.inf, beta=math.inf,
                is_maximising=False,
                my_color=self.piece_type,
                opp_color=opponent,
            )
            if score > best_score:
                best_score = score
                best_pos   = pos

        return StatelessAction({"piece": self.piece_type, "position": best_pos})

    # ------------------------------------------------------------------
    # Minimax with alpha-beta pruning
    # ------------------------------------------------------------------

    def _minimax(self, env, dim_x, dim_y, depth, alpha, beta,
                 is_maximising, my_color, opp_color):

        # Terminal: check if either player has already won
        if _has_won(env, dim_x, dim_y, my_color):
            return  1_000_000
        if _has_won(env, dim_x, dim_y, opp_color):
            return -1_000_000

        empty = [
            (r, c)
            for r in range(dim_x)
            for c in range(dim_y)
            if (r, c) not in env
        ]

        if depth == 0 or not empty or self._out_of_time():
            return self._heuristic(env, dim_x, dim_y, my_color, opp_color)

        # Order + cap moves for performance
        empty = self._order_moves(empty, dim_x, dim_y)[:self.MAX_MOVES]
        color = my_color if is_maximising else opp_color

        if is_maximising:
            value = -math.inf
            for pos in empty:
                new_env = dict(env)
                new_env[pos] = _FakePiece(color)
                value = max(value, self._minimax(
                    new_env, dim_x, dim_y, depth - 1,
                    alpha, beta, False, my_color, opp_color))
                alpha = max(alpha, value)
                if alpha >= beta:
                    break  # β-cut
            return value
        else:
            value = math.inf
            for pos in empty:
                new_env = dict(env)
                new_env[pos] = _FakePiece(color)
                value = min(value, self._minimax(
                    new_env, dim_x, dim_y, depth - 1,
                    alpha, beta, True, my_color, opp_color))
                beta = min(beta, value)
                if alpha >= beta:
                    break  # α-cut
            return value

    # ------------------------------------------------------------------
    # Heuristic: opponent_shortest_path − my_shortest_path
    # ------------------------------------------------------------------

    def _heuristic(self, env, dim_x, dim_y, my_color, opp_color):
        my_dist  = _shortest_path(env, dim_x, dim_y, my_color)
        opp_dist = _shortest_path(env, dim_x, dim_y, opp_color)

        # Guard against infinities (one side completely blocked)
        if opp_dist == math.inf and my_dist == math.inf:
            return 0
        if opp_dist == math.inf:
            return  1_000_000
        if my_dist == math.inf:
            return -1_000_000

        return opp_dist - my_dist

    # ------------------------------------------------------------------
    # Move ordering: rank by heuristic gain (smarter than centre distance)
    # Used at the ROOT only — inner nodes use fast centre-distance ordering
    # ------------------------------------------------------------------

    def _order_moves_by_heuristic(self, moves, env, dim_x, dim_y, my_color, opp_color):
        """
        Score each move by: our heuristic gain + opponent heuristic gain if they played there.
        This ensures we don't ignore moves that block critical opponent threats.
        """
        def move_score(pos):
            # How good is this cell for us?
            env_us = dict(env)
            env_us[pos] = _FakePiece(my_color)
            our_gain = self._heuristic(env_us, dim_x, dim_y, my_color, opp_color)

            # How good would this cell be for the opponent?
            env_opp = dict(env)
            env_opp[pos] = _FakePiece(opp_color)
            opp_gain = self._heuristic(env_opp, dim_x, dim_y, opp_color, my_color)

            return our_gain + opp_gain  # high = important cell for both sides

        return sorted(moves, key=move_score, reverse=True)

    @staticmethod
    def _order_moves(moves, dim_x, dim_y):
        """Fast centre-distance ordering for inner minimax nodes."""
        cx, cy = dim_x / 2, dim_y / 2
        return sorted(moves, key=lambda p: abs(p[0] - cx) + abs(p[1] - cy))


# ======================================================================
# Helpers (module-level, no state)
# ======================================================================

class _FakePiece:
    """Lightweight stand-in for a board piece so we don't need the full env."""
    __slots__ = ("piece_type",)
    def __init__(self, piece_type: str):
        self.piece_type = piece_type


def _shortest_path(env: dict, dim_x: int, dim_y: int, color: str) -> float:
    """
    Dijkstra from all cells on the player's first edge to their second edge.

    R (red)  : connects row 0 → row dim_x-1  (top to bottom, varying row index)
    B (blue) : connects col 0 → col dim_y-1  (left to right, varying col index)

    Edge weights:
        own stone  → 0
        empty cell → 1
        opponent   → ∞ (never traversed)
    """
    INF = math.inf

    def cell_cost(pos):
        piece = env.get(pos)
        if piece is None:
            return 1
        if piece.piece_type == color:
            return 0
        return INF

    def neighbours(r, c):
        for dr, dc in [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < dim_x and 0 <= nc < dim_y:
                yield nr, nc

    # R travels top→bottom: source = all cells in row 0, target = row dim_x-1
    # B travels left→right: source = all cells in col 0, target = col dim_y-1
    if color == "R":
        sources      = [(0, c) for c in range(dim_y)]
        target_check = lambda r, c: r == dim_x - 1
    else:
        sources      = [(r, 0) for r in range(dim_x)]
        target_check = lambda r, c: c == dim_y - 1

    dist = {}
    heap = []
    for pos in sources:
        cost = cell_cost(pos)
        if cost < INF:
            dist[pos] = cost
            heapq.heappush(heap, (cost, pos))

    while heap:
        d, (r, c) = heapq.heappop(heap)
        if d > dist.get((r, c), INF):
            continue
        if target_check(r, c):
            return d
        for nr, nc in neighbours(r, c):
            cost = cell_cost((nr, nc))
            if cost == INF:
                continue
            nd = d + cost
            if nd < dist.get((nr, nc), INF):
                dist[(nr, nc)] = nd
                heapq.heappush(heap, (nd, (nr, nc)))

    return INF


def _has_won(env: dict, dim_x: int, dim_y: int, color: str) -> bool:
    """Flood-fill to check if `color` has a complete connection."""
    # R wins by connecting row 0 → row dim_x-1
    # B wins by connecting col 0 → col dim_y-1
    if color == "R":
        starts = [(0, c) for c in range(dim_y)
                  if env.get((0, c)) and env[(0, c)].piece_type == color]
        goal   = lambda r, c: r == dim_x - 1
    else:
        starts = [(r, 0) for r in range(dim_x)
                  if env.get((r, 0)) and env[(r, 0)].piece_type == color]
        goal   = lambda r, c: c == dim_y - 1

    visited = set()
    stack   = list(starts)
    while stack:
        r, c = stack.pop()
        if (r, c) in visited:
            continue
        visited.add((r, c))
        if goal(r, c):
            return True
        for dr, dc in [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)]:
            nr, nc = r + dr, c + dc
            if (0 <= nr < dim_x and 0 <= nc < dim_y
                    and (nr, nc) not in visited
                    and env.get((nr, nc))
                    and env[(nr, nc)].piece_type == color):
                stack.append((nr, nc))
    return False