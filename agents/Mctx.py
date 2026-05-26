import math
import time
import random
from collections import deque
from player_hex import PlayerHex
from seahorse.game.action import Action
from seahorse.game.game_state import GameState
from seahorse.game.stateless_action import StatelessAction

# Hex MCTS Agent — fixes over previous version:
#   FIX 1: Rollout weights computed ONCE per simulation (not per step)
#   FIX 2: O(1) cell removal via index swap instead of list.remove() O(n)
#   FIX 3: Union-Find for O(α) win detection instead of O(V) flood-fill
#   FIX 4: Correct shortest-path cell detection (fwd + bwd == best)


# ======================================================================
# Module-level helpers
# ======================================================================

class _FakePiece:
    __slots__ = ("piece_type",)
    def __init__(self, piece_type: str):
        self.piece_type = piece_type


# ----------------------------------------------------------------------
# 0-1 BFS — returns full distance dict from source edge
# ----------------------------------------------------------------------

def _bfs_dist(env: dict, dim_x: int, dim_y: int, color: str,
              sources: list) -> dict:
    """Generic 0-1 BFS from `sources`. Returns dist dict."""
    INF = math.inf
    dist = {}
    dq   = deque()

    for pos in sources:
        piece = env.get(pos)
        if piece and piece.piece_type != color:
            continue
        cost = 0 if piece else 1
        if cost < dist.get(pos, INF):
            dist[pos] = cost
            dq.appendleft((cost, pos)) if cost == 0 else dq.append((cost, pos))

    while dq:
        d, (r, c) = dq.popleft()
        if d > dist.get((r, c), INF):
            continue
        for dr, dc in [(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0)]:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < dim_x and 0 <= nc < dim_y):
                continue
            piece = env.get((nr, nc))
            if piece and piece.piece_type != color:
                continue
            cost = 0 if piece else 1
            nd   = d + cost
            if nd < dist.get((nr, nc), INF):
                dist[(nr, nc)] = nd
                dq.appendleft((nd, (nr, nc))) if cost == 0 else dq.append((nd, (nr, nc)))

    return dist


def _path_info(env: dict, dim_x: int, dim_y: int,
               color: str) -> tuple:
    """
    Returns (best_dist, on_path_set) where on_path_set contains empty cells
    that lie on ANY shortest path (correct fwd+bwd check).
    FIX 4: on_path requires fwd[pos] + bwd[pos] - 1 == best, not just fwd < best.
    """
    INF = math.inf

    if color == "R":
        src_fwd  = [(0, c)        for c in range(dim_y)]
        src_bwd  = [(dim_x-1, c)  for c in range(dim_y)]
    else:
        src_fwd  = [(r, 0)        for r in range(dim_x)]
        src_bwd  = [(r, dim_y-1)  for r in range(dim_x)]

    fwd = _bfs_dist(env, dim_x, dim_y, color, src_fwd)
    bwd = _bfs_dist(env, dim_x, dim_y, color, src_bwd)

    if color == "R":
        targets = [(dim_x-1, c) for c in range(dim_y)]
    else:
        targets = [(r, dim_y-1) for r in range(dim_x)]

    best = min((fwd.get(t, INF) for t in targets), default=INF)
    if best == INF:
        return INF, set()

    # FIX 4: cell is on shortest path iff fwd[pos] + bwd[pos] - 1 == best
    # (the -1 corrects for the cell's own cost being counted in both directions)
    on_path = {
        pos for pos, d in fwd.items()
        if not env.get(pos)                     # empty cells only
        and d + bwd.get(pos, INF) - 1 == best
    }
    return best, on_path


# ----------------------------------------------------------------------
# FIX 3: Union-Find for O(α) incremental win detection
# Used inside simulations to avoid O(V) flood-fill after every stone
# ----------------------------------------------------------------------

class _UnionFind:
    """
    Union-Find with virtual nodes for the two edges.
    Virtual node  dim_x * dim_y      = source edge
    Virtual node  dim_x * dim_y + 1  = target edge
    """
    def __init__(self, dim_x: int, dim_y: int):
        self.dim_x   = dim_x
        self.dim_y   = dim_y
        n            = dim_x * dim_y + 2
        self.parent  = list(range(n))
        self.rank    = [0] * n
        self.src     = dim_x * dim_y       # virtual source node
        self.tgt     = dim_x * dim_y + 1   # virtual target node

    def _idx(self, r: int, c: int) -> int:
        return r * self.dim_y + c

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def place(self, r: int, c: int, color: str, env: dict) -> None:
        """
        Place a stone of `color` at (r,c) and union with all same-color neighbours
        and with virtual source/target nodes if on the respective edges.
        """
        dim_x, dim_y = self.dim_x, self.dim_y
        idx = self._idx(r, c)

        # Connect to source/target virtual nodes based on color and position
        if color == "R":
            if r == 0:         self.union(idx, self.src)
            if r == dim_x - 1: self.union(idx, self.tgt)
        else:
            if c == 0:         self.union(idx, self.src)
            if c == dim_y - 1: self.union(idx, self.tgt)

        # Connect to same-color neighbours
        for dr, dc in [(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0)]:
            nr, nc = r + dr, c + dc
            if (0 <= nr < dim_x and 0 <= nc < dim_y):
                piece = env.get((nr, nc))
                if piece and piece.piece_type == color:
                    self.union(idx, self._idx(nr, nc))

    def connected(self) -> bool:
        """True if source and target virtual nodes are connected."""
        return self.find(self.src) == self.find(self.tgt)


# ----------------------------------------------------------------------
# Flood-fill win check (used outside simulation — simpler)
# ----------------------------------------------------------------------

def _has_won(env: dict, dim_x: int, dim_y: int, color: str) -> bool:
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
        for dr, dc in [(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0)]:
            nr, nc = r + dr, c + dc
            if (0 <= nr < dim_x and 0 <= nc < dim_y
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


# ======================================================================
# MCTS Node
# ======================================================================

class _MCTSNode:
    __slots__ = ("env", "dim_x", "dim_y", "move", "color",
                 "parent", "children", "wins", "visits",
                 "untried_moves", "amaf_wins", "amaf_visits")

    def __init__(self, env, dim_x, dim_y, move, color, parent):
        self.env    = env
        self.dim_x  = dim_x
        self.dim_y  = dim_y
        self.move   = move
        self.color  = color
        self.parent = parent

        self.children    = []
        self.wins        = 0.0
        self.visits      = 0
        self.amaf_wins   = {}
        self.amaf_visits = {}

        self.untried_moves = [(r, c) for r in range(dim_x) for c in range(dim_y)
                              if (r, c) not in env]
        random.shuffle(self.untried_moves)

    def ucb_rave(self, child, exploration, rave_k) -> float:
        if child.visits == 0:
            return math.inf
        exploit = child.wins / child.visits
        explore = exploration * math.sqrt(math.log(self.visits) / child.visits)
        ucb     = exploit + explore

        av = self.amaf_visits.get(child.move, 0)
        if av == 0:
            return ucb
        rave = self.amaf_wins.get(child.move, 0) / av
        beta = math.sqrt(rave_k / (3 * self.visits + rave_k))
        return (1 - beta) * ucb + beta * rave

    def is_fully_expanded(self) -> bool:
        return len(self.untried_moves) == 0

    def is_terminal(self) -> bool:
        return (_has_won(self.env, self.dim_x, self.dim_y, "R") or
                _has_won(self.env, self.dim_x, self.dim_y, "B") or
                (not self.untried_moves and not self.children))

    def best_child(self, exploration, rave_k):
        return max(self.children,
                   key=lambda c: self.ucb_rave(c, exploration, rave_k))

    def most_visited_child(self):
        return max(self.children, key=lambda c: c.visits)

    def expand(self, next_color: str):
        pos     = self.untried_moves.pop()
        new_env = dict(self.env)
        new_env[pos] = _FakePiece(next_color)
        child = _MCTSNode(new_env, self.dim_x, self.dim_y,
                          move=pos, color=next_color, parent=self)
        self.children.append(child)
        return child


# ======================================================================
# Agent
# ======================================================================

class MyPlayer(PlayerHex):
    TIME_LIMIT      = 15.0
    MIN_SIMULATIONS = 500
    EXPLORATION     = 1.414
    RAVE_K          = 500
    BIAS_WEIGHT     = 5.0

    def __init__(self, piece_type: str, name: str = "MyPlayer"):
        super().__init__(piece_type, name)

    def compute_action(self, current_state: GameState,
                       remaining_time: int = 1e9, **kwargs) -> Action:
        env   = current_state.rep.env
        dim_x = current_state.rep.dimensions[0]
        dim_y = current_state.rep.dimensions[1]

        moves_played  = len(env)
        moves_left    = max(10, 50 - moves_played)
        dynamic_limit = (remaining_time * 0.85) / moves_left
        time_limit    = min(dynamic_limit, self.TIME_LIMIT)

        possible_actions = list(current_state.get_possible_stateless_actions())
        pos_to_action    = {a.data["position"]: a for a in possible_actions}

        def pick(pos):
            return pos_to_action.get(pos, possible_actions[0])

        if self.piece_type == "R" and len(env) == 0:
            return pick((1, 1))

        if self.piece_type == "B" and len(env) == 1:
            opp_pos = list(env.keys())[0]
            if _is_strong_opening(opp_pos, dim_x, dim_y):
                return pick(opp_pos)

        opponent  = "B" if self.piece_type == "R" else "R"
        best_move = self._mcts(env, dim_x, dim_y,
                               self.piece_type, opponent, time_limit)
        return pick(best_move)

    # ------------------------------------------------------------------
    # MCTS loop
    # ------------------------------------------------------------------

    def _mcts(self, env, dim_x, dim_y, my_color, opp_color, time_limit) -> tuple:
        root        = _MCTSNode(env, dim_x, dim_y,
                                move=None, color=opp_color, parent=None)
        root.visits = 1
        deadline    = time.time() + time_limit
        iterations  = 0

        while time.time() < deadline or iterations < self.MIN_SIMULATIONS:
            node = self._select(root)

            next_color = opp_color if node.color == my_color else my_color
            if not node.is_terminal() and not node.is_fully_expanded():
                node       = node.expand(next_color)
                next_color = opp_color if node.color == my_color else my_color

            winner, sim_moves = self._simulate(
                node.env, dim_x, dim_y, next_color, my_color, opp_color)

            self._backprop(node, winner, my_color, sim_moves)
            iterations += 1

        print(f"[MCTS] {iterations} iterations, time_limit={time_limit:.1f}s")
        return root.most_visited_child().move

    def _select(self, node: _MCTSNode) -> _MCTSNode:
        while node.is_fully_expanded() and node.children:
            node = node.best_child(self.EXPLORATION, self.RAVE_K)
        return node

    # ------------------------------------------------------------------
    # FIX 1 + FIX 2 + FIX 3: Fast simulation
    # ------------------------------------------------------------------

    def _simulate(self, env: dict, dim_x: int, dim_y: int,
                  color_to_move: str, my_color: str, opp_color: str) -> tuple:
        """
        FIX 1: Compute rollout weights ONCE before the loop (not per step).
        FIX 2: Use index-swap removal O(1) instead of list.remove() O(n).
        FIX 3: Use Union-Find for O(α) win detection instead of flood-fill O(V).
        """
        sim_env   = dict(env)
        color     = color_to_move
        sim_moves = []

        # FIX 1: compute path cells once, before the playout loop
        _, on_path_my  = _path_info(sim_env, dim_x, dim_y, my_color)
        _, on_path_opp = _path_info(sim_env, dim_x, dim_y, opp_color)
        important      = on_path_my | on_path_opp

        # FIX 2: build list + index for O(1) removal via swap-and-pop
        empty = [pos for pos in
                 ((r, c) for r in range(dim_x) for c in range(dim_y))
                 if pos not in sim_env]
        pos_index = {pos: i for i, pos in enumerate(empty)}

        # FIX 3: one Union-Find per color for incremental win detection
        uf_my  = _UnionFind(dim_x, dim_y)
        uf_opp = _UnionFind(dim_x, dim_y)

        # Seed Union-Find with stones already on the board
        for (r, c), piece in sim_env.items():
            if piece.piece_type == my_color:
                uf_my.place(r, c, my_color, sim_env)
            elif piece.piece_type == opp_color:
                uf_opp.place(r, c, opp_color, sim_env)

        while empty:
            # Weighted choice: important cells get BIAS_WEIGHT, rest get 1
            weights = [self.BIAS_WEIGHT if pos in important else 1.0
                       for pos in empty]
            pos = random.choices(empty, weights=weights, k=1)[0]

            # FIX 2: O(1) removal via swap-and-pop
            i          = pos_index[pos]
            last       = empty[-1]
            empty[i]   = last
            pos_index[last] = i
            empty.pop()
            del pos_index[pos]

            # Place stone
            sim_env[pos] = _FakePiece(color)
            sim_moves.append((pos, color))
            r, c = pos

            # FIX 3: update Union-Find and check win in O(α)
            if color == my_color:
                uf_my.place(r, c, my_color, sim_env)
                if uf_my.connected():
                    return my_color, sim_moves
            else:
                uf_opp.place(r, c, opp_color, sim_env)
                if uf_opp.connected():
                    return opp_color, sim_moves

            color = opp_color if color == my_color else my_color

        winner = my_color if uf_my.connected() else opp_color
        return winner, sim_moves

    # ------------------------------------------------------------------
    # Backprop with RAVE
    # ------------------------------------------------------------------

    def _backprop(self, node: _MCTSNode, winner: str,
                  my_color: str, sim_moves: list) -> None:
        while node is not None:
            node.visits += 1
            if node.color == winner:
                node.wins += 1

            next_color = my_color if node.color != my_color else \
                         ("B" if my_color == "R" else "R")

            for pos, color in sim_moves:
                if color == next_color:
                    node.amaf_visits[pos] = node.amaf_visits.get(pos, 0) + 1
                    if color == winner:
                        node.amaf_wins[pos] = node.amaf_wins.get(pos, 0) + 1

            node = node.parent