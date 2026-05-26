import random
from player_hex import PlayerHex
from game_state_hex import GameStateHex
from seahorse.game.action import Action


class MyPlayer(PlayerHex):
    """
    Player class for Hex game that makes random moves.

    Attributes:
        piece_type (str): piece type of the player
    """

    def __init__(self, piece_type: str, name: str = "bob", *args) -> None:
        """
        Initialize the PlayerHex instance.

        Args:
            piece_type (str): Type of the player's game piece "R" or "B"
            name (str, optional): Name of the player (default is "bob")
            time_limit (float, optional): the time limit in (s)
        """
        super().__init__(piece_type, name, *args)

    def compute_action(self, current_state: GameStateHex, **kwargs) -> Action:
        """
        Function to implement the logic of the player (here random selection of a feasible solution).

        Args:
            current_state (GameState): Current game state representation
            **kwargs: Additional keyword arguments

        Returns:
            Action: Randomly selected feasible action
        """
        possible_actions = current_state.get_possible_stateful_actions()
        action = random.choice(list(possible_actions))
        return action
