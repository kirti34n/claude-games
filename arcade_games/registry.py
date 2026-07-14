"""The game catalog: icons, the menu list, the CLI alias map, and the title
banner (play.py 3595-3635, 3769-3773).

Imports the 14 game classes from arcade_games.games.*; this module is the
one place that knows about all of them, so net.py and menu.py/cli.py import
the class list from here rather than reaching into arcade_games.games
directly (keeps the dependency graph acyclic).
"""
from .games.snake import SnakeGame
from .games.tetris import TetrisGame
from .games.g2048 import Game2048
from .games.dino import DinoGame
from .games.breakout import BreakoutGame
from .games.shooter import ShooterGame
from .games.pong import PongGame
from .games.flappy import FlappyGame
from .games.minesweeper import MinesweeperGame
from .games.pacman import PacManGame
from .games.sokoban import SokobanGame
from .games.reversi import ReversiGame
from .games.frogger import FroggerGame
from .games.connect4 import ConnectFourGame

_ICONS = {'snake': '~o~', 'tetris': '[#]', '2048': ' 2K', 'dino': '/^\\',
          'breakout': '[=]', 'shooter': '/A\\', 'pong': '|O|',
          'flappy': '>>=', 'minesweeper_i': '[*]', 'pacman': 'C.M',
          'sokoban': '[$]', 'reversi': 'XO ', 'frogger': '@^^',
          'connect4': 'OXO'}

_GAMES = [
    ("Snake",         "Classic snake - eat food, grow longer",     SnakeGame),
    ("Tetris",        "Stack blocks, clear lines",                 TetrisGame),
    ("2048",          "Slide and merge tiles to reach 2048",       Game2048),
    ("Dino Runner",   "Jump over obstacles, survive!",             DinoGame),
    ("Breakout",      "Break all the bricks with a bouncing ball", BreakoutGame),
    ("Space Shooter", "Blast enemies, defeat bosses",              ShooterGame),
    ("Pong",          "Classic paddle game vs AI",                 PongGame),
    ("Flappy Bird",   "Flap through pipes, don't crash",          FlappyGame),
    ("Minesweeper",   "Uncover cells, avoid mines",               MinesweeperGame),
    ("Pac-Man",       "Eat dots, avoid ghosts",                   PacManGame),
    ("Sokoban",       "Push every box onto a target",             SokobanGame),
    ("Reversi",       "Outflank the AI on an 8x8 board",          ReversiGame),
    ("Frogger",       "Hop across road and river to the bays",    FroggerGame),
    ("Connect Four",  "Drop discs, get four in a row (vs AI)",    ConnectFourGame),
]

_TITLE = [
    " ╔═╗╦═╗╔═╗╔═╗╔╦╗╔═╗ ",
    " ╠═╣╠╦╝║  ╠═╣ ║║║╣  ",
    " ╩ ╩╩ ╩╚═╝╩ ╩═╩╝╚═╝ ",
]

_GAME_MAP = {g[0].lower().replace(' ', ''): g[2] for g in _GAMES}
_GAME_MAP.update({'dino': DinoGame, '2048': Game2048,
                  'shooter': ShooterGame, 'space': ShooterGame,
                  'pong': PongGame, 'flappy': FlappyGame,
                  'bird': FlappyGame, 'mines': MinesweeperGame,
                  'sweep': MinesweeperGame, 'pacman': PacManGame,
                  'pac': PacManGame, 'sokoban': SokobanGame,
                  'boxes': SokobanGame, 'reversi': ReversiGame,
                  'othello': ReversiGame, 'frogger': FroggerGame,
                  'frog': FroggerGame, 'connect4': ConnectFourGame,
                  'connectfour': ConnectFourGame, 'c4': ConnectFourGame})

_NET_GAMES = [
    ('Reversi', ReversiGame, 'reversi'),
    ('Connect Four', ConnectFourGame, 'connect4'),
    ('Pong', PongGame, 'pong'),
]
