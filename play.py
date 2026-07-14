"""
play - Terminal mini games collection

This module is a thin backwards-compatible shim: the real implementation now
lives in the arcade_games package. It re-exports the public names so
`python play.py` and existing scripts/tests that do `import play` keep
working unchanged. See arcade_games/main.py for the CLI docstring/usage.
"""
from arcade_games._version import __version__
from arcade_games import config
from arcade_games.config import (
    CONFIG_DIR, SCORES_FILE, GAME_STATE_FILE,
    load_high_score, save_high_score,
)
from arcade_games.game import Game
from arcade_games.games.snake import SnakeGame
from arcade_games.games.tetris import TetrisGame
from arcade_games.games.g2048 import Game2048
from arcade_games.games.dino import DinoGame, _CACTUS_SM, _CACTUS_LG, _CACTUS_XL
from arcade_games.games.breakout import BreakoutGame
from arcade_games.games.shooter import ShooterGame
from arcade_games.games.pong import PongGame
from arcade_games.games.flappy import FlappyGame
from arcade_games.games.minesweeper import MinesweeperGame
from arcade_games.games.pacman import PacManGame
from arcade_games.games.sokoban import SokobanGame
from arcade_games.games.reversi import ReversiGame
from arcade_games.games.frogger import FroggerGame
from arcade_games.games.connect4 import ConnectFourGame
from arcade_games.registry import _ICONS, _GAMES, _GAME_MAP, _TITLE, _NET_GAMES
from arcade_games.menu import _menu, _run_game
from arcade_games.net import _NetLink, _net_menu
from arcade_games.cli import (
    _cli_snake_move, _cli_snake_init, _cli_snake_render,
    _cli_2048_init, _cli_2048_move, _cli_2048_render,
    _cli_ms_init, _cli_ms_move, _cli_ms_render,
    _cli_c4_init, _cli_c4_move, _cli_c4_render, _cli_c4_check_win,
    _cli_c4_ai_move, _cli_mode,
)
from arcade_games.main import main

if __name__ == '__main__':
    main()
