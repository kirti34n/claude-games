# play - Terminal Mini Games

<p align="center">
  <img src="https://img.shields.io/badge/python-3.7+-blue.svg" alt="Python 3.7+">
  <img src="https://img.shields.io/badge/dependencies-zero-green.svg" alt="Zero Dependencies">
  <img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20WSL-lightgrey.svg" alt="Platform">
</p>

<p align="center">
  7 classic games in your terminal. Zero dependencies. Just <code>play</code>.
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
 Space               Jump (Dino) / Hard Drop (Tetris) / Launch (Breakout) / Fire (Shooter) / Serve (Pong)
 W                   Rotate (Tetris)
 P                   Pause
 ESC / Q             Quit (auto-saves progress)
 ?/H                 Show controls help
 R                   Retry after game over
```

## Features

- **Auto-save** — Quit mid-game with ESC, resume next time you play
- **High scores** — Tracked per game, shown in menu
- **Zero dependencies** — Pure Python, just curses (built-in)
- **Single file** — Entire codebase is one `play.py`
- **Difficulty selection** — Choose Easy/Medium/Hard for Shooter and Pong
- **In-game help** — Press `?` during any game to see controls
- **Adaptive difficulty** — Snake speeds up as you score, Tetris levels up
- **Ghost piece** — Tetris shows where your piece will land
- **Works everywhere** — Linux, macOS, WSL2

## Claude Code Integration

Works as a slash command inside [Claude Code](https://claude.ai/claude-code) — play games while Claude works in the background.

```
/play snake         # Launch a game
! play              # Open game menu directly
```

**Turn-based CLI mode** for in-conversation play (no terminal needed):

```bash
play cli start snake       # Start a CLI game
play cli start 2048        # Start 2048
play cli start minesweeper # Start Minesweeper
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
│   └── Pong
├── CLI Games (turn-based)         # Text output, no curses needed
│   ├── Snake
│   ├── 2048
│   └── Minesweeper
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
