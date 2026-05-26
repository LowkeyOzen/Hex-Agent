from __future__ import annotations
import json
from typing import Generator
from colorama import Fore, Style
from seahorse.game.game_layout.board import Board, Piece

class BoardHex(Board):
    """
    A class representing an Hex board.

    Attributes:
        env (dict[tuple[int], Piece]): The environment dictionary composed of pieces.
        dimension (int): The dimension of the board.
    """

    def __init__(self, env: dict[tuple[int], Piece], dim: list[int]) -> None:
        super().__init__(env, dim)

    def __str__(self):
        grid_data = self.get_grid()
        board_string = ""
        for i in range(self.dimensions[0]):
            board_string += " " * i
            for j in range(self.dimensions[1]):
                cell = grid_data[i][j]
                if isinstance(cell, tuple):
                    char, color = cell
                    if color == 'R':
                        board_string += Fore.RED + char + Style.RESET_ALL + " "
                    elif color == 'B':
                        board_string += Fore.BLUE + char + Style.RESET_ALL + " "
                else:
                    board_string += cell + " "
            board_string += "\n"
        return board_string
    
    def get_neighbours(self, i:int ,j: int) -> dict[str,tuple[str|Piece,tuple[int,int]]]:
        """ returns a dictionnary of the neighbours of the cell (i,j) with the following format:
        (neighbour_name: (neighbour_type, (i,j)))

        Args:
            i (int): line indice
            j (int): column indice

        Returns:
            dict[str,tuple[str,tuple[int,int]]]: dictionnary of the neighbours of the cell (i,j)
        """
        positions = {"top_right":(i-1, j+1), "top_left":(i-1,j), 
                     "bot_left":(i+1, j-1), "bot_right":(i+1,j), 
                     "left":(i,j-1), "right":(i,j+1)}
        neighbours: dict[str,tuple[str|Piece,tuple[int,int]]] = {}
        for k,v in positions.items():
            if v not in self.env.keys():
                if v[0] < 0 or v[1] < 0 or v[0] >= self.dimensions[0] or v[1] >= self.dimensions[1]:
                    neighbours[k] = ("OUTSIDE", positions[k])
                else:
                    neighbours[k] = ("EMPTY",positions[k])
            else:
                neighbours[k] = (self.env[v].get_type(),v)
        return neighbours

    def get_grid(self) -> list[list[int|str|tuple[str,str]]]:
        """
        Return a nice representation of the board.

        Returns:
            str: The nice representation of the board.
        """
        grid_data: list[list[int|str|tuple[str,str]]] = [[0 for _ in range(self.dimensions[1])] for _ in range(self.dimensions[0])]
        for i in range(self.dimensions[0]):
            for j in range(self.dimensions[1]):
                if (i,j) in self.env:
                    piece_type = self.env[(i,j)].get_type()
                    grid_data[i][j] = ("⬢", piece_type)
                else:
                    grid_data[i][j] = " "
         
        return grid_data
    
    def get_empty(self) -> Generator[tuple[int, int], None, None]:
        """
        Returns a list of empty cells in the grid.

        Returns:
            list[tuple[int, int]]: A list of tuples representing the coordinates of empty cells.
        """
        for i in range(self.dimensions[0]):
            for j in range(self.dimensions[1]):
                if (i,j) not in self.env:
                    yield (i,j)
       
    def to_json(self) -> dict:
        """
        Converts the board to a JSON object.

        Returns:
            dict: The JSON representation of the board.
        """
        return {"env":{str(x):y.to_json() for x,y in self.env.items()},"dim":self.dimensions}

    @classmethod
    def from_json(cls, data: str | dict) -> BoardHex:
        if isinstance(data, str):
            data = json.loads(data)
        else:
            data = data

        return cls(**{
            "env": {eval(x): Piece.from_json(y)
                    for x, y in data["env"].items()},
            "dim": data["dim"]
        })
