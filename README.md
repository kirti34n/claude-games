# play - Terminal Mini Games

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20WSL%20%7C%20Windows-lightgrey.svg" alt="Platform">
</p>

<p align="center">
  13 classic games in your terminal. Just <code>play</code>.
</p>

---

```
 ╔═╗╦  ╔═╗╦ ╦╔╦╗╔═╗  ╔═╗╔═╗╔╦╗╔═╗╔═╗
 ║  ║  ╠═╣║ ║ ║║║╣   ║ ╦╠═╣║║║║╣ ╚═╗
 ╚═╝╩═╝╩ ╩╚═╝═╩╝╚═╝  ╚═╝╩ ╩╩ ╩╚═╝╚═╝
            Play while you wait
```

## Install

```bash
pip install claude-games
```

The full-screen games use Python's `curses`. It's built in on Linux/macOS; on
Windows the install also pulls in `windows-curses` automatically. The turn-based
`play cli` games need no curses at all.

Or from source:

```bash
git clone https://github.com/kirti34n/claude-games.git
cd claude-games
pip install .
```

## Games

| Game | Preview | Description |
|------|---------|-------------|
| **Snake** | `play snake` | Eat food, grow longer, don't hit walls |
| **Tetris** | `play tetris` | Stack blocks, clear lines, level up |
| **2048** | `play 2048` | Slide and merge tiles to reach 2048 |
| **Dino Runner** | `play dino` | Jump over cacti, survive as long as you can |
| **Breakout** | `play breakout` | Smash bricks with a bouncing ball |
| **Space Shooter** | `play shooter` | Blast enemies, defeat bosses |
| **Pong** | `play pong` | Classic paddle game vs AI |
| **Flappy Bird** | `play flappy` | Flap through pipes, don't crash |
| **Minesweeper** | `play mines` | Uncover cells, avoid mines |
| **Pac-Man** | `play pacman` | Eat dots, avoid ghosts |
| **Sokoban** | `play sokoban` | Push every box onto a target |
| **Reversi** | `play reversi` | Outflank the AI on an 8x8 board |
| **Frogger** | `play frogger` | Cross the road and river to the home bays |

## Quick Start

```bash
play              # Open game menu
play snake        # Jump straight into Snake
play tetris       # Jump straight into Tetris
play list         # See all games + high scores
```

## Controls

```
 WASD / Arrow Keys   Move / Navigate
 Space               Jump (Dino) / Hard Drop (Tetris) / Launch (Breakout) / Fire (Shooter) / Serve (Pong) / Place (Reversi)
 W                   Rotate (Tetris)
 P                   Pause
 ESC / Q             Quit (auto-saves progress)
 ?/H                 Show controls help
 F                   Flag (Minesweeper)
 U                   Undo (Sokoban)
 R                   Reset level (Sokoban) / Retry after game over
 T                   Cycle color theme (menu)
```

## Features

- **Auto-save**: Quit mid-game with ESC, resume next time you play
- **High scores**: Tracked per game, shown in menu
- **Pure Python**: No third-party deps on Linux/macOS (Windows pulls in `windows-curses`)
- **Single file**: Entire codebase is one `play.py`
- **Difficulty selection**: Choose Easy/Medium/Hard for Shooter and Pong
- **In-game help**: Press `?` during any game to see controls
- **Color themes**: Cycle themes with T in the menu (default, retro, ocean)
- **Sound effects**: Terminal beep on new high scores
- **Adaptive difficulty**: Snake speeds up as you score, Tetris levels up
- **Ghost piece**: Tetris shows where your piece will land
- **Works everywhere**: Linux, macOS, WSL2, Windows

## Claude Code Integration

Run it from inside [Claude Code](https://claude.ai/claude-code) with the `!` bash prefix: play while Claude works in the background.

```
! play snake        # Launch a game in a new window / split pane
! play              # Open the game menu
```

**Turn-based CLI mode** for in-conversation play (no terminal needed):

```bash
play cli start snake       # Start a CLI game
play cli start 2048        # Start 2048
play cli start minesweeper # Start Minesweeper
play cli start connect4    # Start Connect4
play w                     # Move up (WASD shortcuts)
play show                  # Show current board
play quit                  # End game
```

## How It Works

```
play.py (single file)
├── Interactive Games (curses)     # Full-screen, real-time
│   ├── Snake
│   ├── Tetris
│   ├── 2048
│   ├── Dino Runner
│   ├── Breakout
│   ├── Space Shooter
│   ├── Pong
│   ├── Flappy Bird
│   ├── Minesweeper
│   ├── Pac-Man
│   ├── Sokoban
│   ├── Reversi
│   └── Frogger
├── CLI Games (turn-based)         # Text output, no curses needed
│   ├── Snake
│   ├── 2048
│   ├── Minesweeper
│   └── Connect4
├── Game Menu                      # Arrow keys to select
├── Save/Resume System             # JSON state files
└── Smart Terminal Detection       # Opens new window if no TTY
```

## Config

High scores and saves stored in `~/.config/claude-games/`:

```
~/.config/claude-games/
├── scores.json         # High scores
├── current_game.json   # CLI game state
├── save_snake.json     # Auto-save (created on ESC)
└── save_tetris.json    # ...etc
```

## License

MIT
