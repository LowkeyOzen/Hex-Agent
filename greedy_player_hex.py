import numpy as np
import heapq
from player_hex import PlayerHex
from game_state_hex import GameStateHex
from seahorse.game.action import Action
from seahorse.game.stateless_action import StatelessAction

class MyPlayer(PlayerHex):
    """
    Player class for Hex game that makes greedy moves.

    Attributes:
        piece_type (str): piece type of the player
    """

    def __init__(self, piece_type: str, name: str = "bob",*args) -> None:
        """
        Initialize the PlayerHex instance.

        Args:
            piece_type (str): Type of the player's game piece "R" or "B"
            name (str, optional): Name of the player (default is "bob")
            time_limit (float, optional): the time limit in (s)
        """
        super().__init__(piece_type,name,*args)

    def compute_action(self, current_state: GameStateHex, **_kwargs) -> Action:
        """
        Function to implement the logic of the player (here greedy selection of a feasible solution).

        Args:
            current_state (GameState): Current game state representation
            **kwargs: Additional keyword arguments

        Returns:
            Action: Greedily selected feasible action
        """
        _possible_actions = current_state.get_possible_stateless_actions()

        # Greedily find a shortest path connecting the 2 sides, and play closest to the center on it.
        env = current_state.rep.env
        dist = np.full((current_state.rep.dimensions[0], current_state.rep.dimensions[1]), np.inf)
        preds = np.full((current_state.rep.dimensions[0], current_state.rep.dimensions[1]), None, dtype=tuple)
        objectives = []
        pq = []
        if self.piece_type == "R":
            for j in range(current_state.rep.dimensions[1]):
                objectives.append((current_state.rep.dimensions[0]-1, j))
                if env.get((0,j)) is None:
                    dist[0, j] = 1
                elif env.get((0,j)).piece_type == "R":
                    dist[0, j] = 0
                else:
                    continue
                heapq.heappush(pq, (dist[0, j], (0, j), None))


        else:
            for i in range(current_state.rep.dimensions[0]):
                objectives.append((i, current_state.rep.dimensions[1]-1))
                if env.get((i,0)) is None:
                    dist[i, 0] = 1
                elif env.get((i,0)).piece_type == "B":
                    dist[i, 0] = 0
                else:
                    continue
                heapq.heappush(pq, (dist[i, 0], (i, 0), None))

        path=[]
        while len(pq) != 0:
            d, (i, j), pred = heapq.heappop(pq)
            if d > dist[i, j]:
                continue
            preds[i,j] = pred
            if (i,j) in objectives:
                path = retrace_path(preds, (i,j))
                break
            for n_type, (ni, nj) in current_state.rep.get_neighbours(i, j).values():
                if n_type == "EMPTY":
                    new_dist = d + 1
                elif n_type == self.piece_type:
                    new_dist = d 
                else:
                    continue
                if new_dist < dist[ni, nj]:
                    dist[ni, nj] = new_dist
                    heapq.heappush(pq, (new_dist, (ni, nj), (i, j)))
        
        hq = []
        for pos in path:
            if env.get(pos) == None:
                heapq.heappush(hq, (abs(pos[0]-6.5) + abs(pos[1]-6.5), pos))
        _ , pos = heapq.heappop(hq)
        return StatelessAction({"piece": self.piece_type, "position": pos})

def retrace_path(preds, end):
    """
    Recreate the path from the start to the end position using the predecessors.
    """
    path = []
    current = end
    while current is not None:
        path.append(current)
        current = preds[current]
    return path
