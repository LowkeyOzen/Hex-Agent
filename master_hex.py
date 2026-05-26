from typing import Iterable

from player_hex import PlayerHex
from game_state_hex import GameStateHex

from seahorse.game.master import GameMaster
from seahorse.player.proxies import PlayerProxy


class MasterHex(GameMaster):
    """
    Master to play the game Hex

    Attributes:
        name (str): Name of the game
        initial_game_state (GameState): Initial state of the game
        current_game_state (GameState): Current state of the game
        players_iterator (Iterable): An iterable for the players_iterator, ordered according to the playing order.
            If a list is provided, a cyclic iterator is automatically built
        log_level (str): Name of the log file
    """

    def __init__(self, name: str, initial_game_state: GameStateHex,
                 players_iterator: Iterable[PlayerProxy],
                 log_level: str, port: int = 8080,
                 hostname: str = "localhost", time_limit: int = 60*15) -> None:
        super().__init__(name, initial_game_state, players_iterator,
                         log_level, port, hostname, time_limit)

    def compute_winner(self) -> list[PlayerHex]:
        """
        Computes the winners of the game based on the scores.

        Args:
            scores (Dict[int, float]): Score for each player

        Returns:
            Iterable[Player]: list of the players who won the game
        """
        scores = self.current_game_state.get_scores()
        max_val = max(scores.values())
        players_id = list(filter(lambda key: scores[key] == max_val, scores))
        itera = list(filter(lambda x: x.get_id() in players_id, self.players))
        return itera

    def get_custom_stats(self):
        return [{"name": "coups",
                 "value": self.current_game_state.get_step(), "agent_id": -1}]
