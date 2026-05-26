from __future__ import annotations

import json

from seahorse.player.player import Player

class PlayerHex(Player):
    """
    A player class for the Hex game.

    Attributes:
        piece_type (str): piece type of the player
    """

    def __init__(self, piece_type: str, name: str = "bob", *args, **kwargs) -> None:
        """
        Initializes a new instance of the PlayerHex class.

        Args:
            piece_type (str): The type of the player's game piece.
            name (str, optional): The name of the player. Defaults to "bob".
        """
        super().__init__(name,*args,**kwargs)
        self.piece_type = piece_type # Blue or Red (B or R)
    
    def get_piece_type(self) -> str:
        """
        Gets the type of the player's game piece.

        Returns:
            str: The type of the player's game piece.
        """
        return self.piece_type

    def set_piece_type(self, piece_type: str) -> None:
        """
        Sets the type of the player's game piece.

        Args:
            piece_type (str): The type of the player's game piece.
        """
        if piece_type not in ["R", "B"]:
            raise ValueError("Piece type must be 'R' or 'B'.")
        self.piece_type = piece_type
    
    def to_json(self) -> dict:
        return {i:j for i,j in self.__dict__.items() if not i.startswith("_")}

    @classmethod
    def from_json(cls, data) -> PlayerHex:
        if isinstance(data, str):
            data = json.loads(data)
        return PlayerHex(**data)
