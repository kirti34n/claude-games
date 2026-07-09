<div align="center">

# ▶ play &nbsp;·&nbsp; Terminal Mini Games

<em>13 classic games in your terminal. One command. Zero setup.</em>

<img src="https://img.shields.io/badge/python-3.8+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.8+">
<img src="https://img.shields.io/badge/games-13-brightgreen.svg" alt="13 games">
<img src="https://img.shields.io/badge/dependencies-0%20on%20Linux%2FmacOS-success.svg" alt="Zero deps on Linux/macOS">
<img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License">
<img src="https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20WSL%20·%20Windows-lightgrey.svg" alt="Platform">

<br><br>

<table>
<tr>
<td align="center"><img src="assets/pacman.gif" width="360" alt="Pac-Man"></td>
<td align="center"><img src="assets/tetris.gif" width="360" alt="Tetris"></td>
</tr>
</table>

</div>

```
 ╔═╗╦  ╔═╗╦ ╦╔╦╗╔═╗  ╔═╗╔═╗╔╦╗╔═╗╔═╗
 ║  ║  ╠═╣║ ║ ║║║╣   ║ ╦╠═╣║║║║╣ ╚═╗
 ╚═╝╩═╝╩ ╩╚═╝═╩╝╚═╝  ╚═╝╩ ╩╩ ╩╚═╝╚═╝
            Play while you wait
```

## Contents

[Install](#install) · [Games](#games) · [Controls](#controls) · [Features](#features) · [Turn-based CLI mode](#turn-based-cli-mode) · [Development](#development) · [Contributing](#contributing) · [License](#license)

## Install

```bash
pip install claude-games
```

Then just:

```bash
play              # open the game menu
play snake        # jump straight into a game
play list         # list every game and your high scores
```

The full-screen games use Python's built-in `curses`. It ships with Python on
Linux and macOS; on Windows the install also pulls in `windows-curses`
automatically. The turn-based [CLI mode](#turn-based-cli-mode) needs no curses at all.

<details>
<summary>Install from source</summary>

```bash
git clone https://github.com/kirti34n/claude-games.git
cd claude-games
pip install .
```
</details>

## Games

### Arcade

<table>
<tr>
<td width="50%" align="center">
<img src="assets/snake.gif" width="400" alt="Snake"><br>
<b>Snake</b> &nbsp;·&nbsp; <code>play snake</code><br>
<sub>Eat food, grow longer, don't hit a wall. Speeds up as you score.</sub>
</td>
<td width="50%" align="center">
<img src="assets/pacman.gif" width="400" alt="Pac-Man"><br>
<b>Pac-Man</b> &nbsp;·&nbsp; <code>play pacman</code><br>
<sub>Eat the dots, grab a power pellet, and outrun four ghosts.</sub>
</td>
</tr>
<tr>
<td width="50%" align="center">
<img src="assets/dino.gif" width="400" alt="Dino Runner"><br>
<b>Dino Runner</b> &nbsp;·&nbsp; <code>play dino</code><br>
<sub>Jump the cacti and survive as long as you can.</sub>
</td>
<td width="50%" align="center">
<img src="assets/breakout.gif" width="400" alt="Breakout"><br>
<b>Breakout</b> &nbsp;·&nbsp; <code>play breakout</code><br>
<sub>Smash every brick with a bouncing ball.</sub>
</td>
</tr>
<tr>
<td width="50%" align="center">
<img src="assets/shooter.gif" width="400" alt="Space Shooter"><br>
<b>Space Shooter</b> &nbsp;·&nbsp; <code>play shooter</code><br>
<sub>Blast waves of enemies, grab power-ups, defeat bosses.</sub>
</td>
<td width="50%" align="center">
<img src="assets/flappy.gif" width="400" alt="Flappy Bird"><br>
<b>Flappy Bird</b> &nbsp;·&nbsp; <code>play flappy</code><br>
<sub>Flap through the gaps and don't crash.</sub>
</td>
</tr>
<tr>
<td align="center" colspan="2">
<img src="assets/frogger.gif" width="400" alt="Frogger"><br>
<b>Frogger</b> &nbsp;·&nbsp; <code>play frogger</code><br>
<sub>Hop across the traffic and the log-choked river to the home bays.</sub>
</td>
</tr>
</table>

### Puzzle

<table>
<tr>
<td width="50%" align="center">
<img src="assets/tetris.gif" width="400" alt="Tetris"><br>
<b>Tetris</b> &nbsp;·&nbsp; <code>play tetris</code><br>
<sub>Stack the blocks, clear lines, level up. With a ghost piece.</sub>
</td>
<td width="50%" align="center">
<img src="assets/2048.gif" width="400" alt="2048"><br>
<b>2048</b> &nbsp;·&nbsp; <code>play 2048</code><br>
<sub>Slide and merge tiles to reach 2048.</sub>
</td>
</tr>
<tr>
<td width="50%" align="center">
<img src="assets/minesweeper.gif" width="400" alt="Minesweeper"><br>
<b>Minesweeper</b> &nbsp;·&nbsp; <code>play mines</code><br>
<sub>Uncover the board, flag the mines. Easy / Medium / Hard.</sub>
</td>
<td width="50%" align="center">
<img src="assets/sokoban.gif" width="400" alt="Sokoban"><br>
<b>Sokoban</b> &nbsp;·&nbsp; <code>play sokoban</code><br>
<sub>Push every box onto a target. Undo any time.</sub>
</td>
</tr>
</table>

### Head-to-head

<table>
<tr>
<td width="50%" align="center">
<img src="assets/pong.gif" width="400" alt="Pong"><br>
<b>Pong</b> &nbsp;·&nbsp; <code>play pong</code><br>
<sub>Classic paddle duel vs a reactive AI. Easy / Medium / Hard.</sub>
</td>
<td width="50%" align="center">
<img src="assets/reversi.gif" width="400" alt="Reversi"><br>
<b>Reversi</b> &nbsp;·&nbsp; <code>play reversi</code><br>
<sub>Outflank a positional AI on an 8x8 board. Corners win games.</sub>
</td>
</tr>
</table>

> There is also a **Connect Four** in the [turn-based CLI mode](#turn-based-cli-mode).

## Controls

```
 WASD / Arrow keys   Move · navigate menus
 Space               Context action: Jump (Dino) · Hard drop (Tetris) ·
                     Launch (Breakout) · Fire (Shooter) · Serve (Pong) ·
                     Place (Reversi) · Reveal (Minesweeper)
 W                   Rotate (Tetris)
 F                   Flag a cell (Minesweeper)
 U                   Undo a move (Sokoban)
 R                   Reset level (Sokoban) · Retry after game over
 P                   Pause
 ? / H               Show the in-game controls
 T                   Cycle color theme (in the menu)
 ESC / Q             Quit (your progress is auto-saved)
```

## Features

- **Auto-save & resume** &nbsp; Quit any game with `ESC` and pick up exactly where you left off.
- **High scores** &nbsp; Tracked per game and shown in the menu.
- **13 games, one file** &nbsp; The entire project is a single `play.py`.
- **Runs everywhere** &nbsp; Linux, macOS, WSL, and Windows.
- **Zero third-party deps** on Linux/macOS (Windows just adds `windows-curses`).
- **Difficulty levels** &nbsp; Choose Easy / Medium / Hard for Space Shooter, Pong, and Minesweeper.
- **Color themes** &nbsp; Cycle `default`, `retro`, and `ocean` with `T` in the menu.
- **In-game help** &nbsp; Press `?` in any game for its controls.
- **Adaptive difficulty** &nbsp; Snake, Dino, and Flappy speed up as you go; Tetris levels up.
- **Ghost piece** &nbsp; Tetris shows where the current piece will land.

## Turn-based CLI mode

A text-only mode that needs no terminal UI (and no curses), handy for playing
one move at a time, for example inside a chat or an editor.

<div align="center">
<img src="assets/cli-connect4.gif" width="300" alt="Connect Four in the turn-based CLI mode"><br>
<sub>Connect Four vs the AI, one <code>play &lt;column&gt;</code> at a time</sub>
</div>

```bash
play cli start snake         # also: 2048, minesweeper, connect4
play w                       # move (WASD), or up / down / left / right
play show                    # reprint the current board
play reveal 5 5              # Minesweeper: reveal row 5, col 5 (first click is always safe)
play flag 3 4                # Minesweeper: toggle a flag
play 4                       # Connect Four: drop a disc in column 4
play quit                    # end the game
```

## Development

The whole thing is one file, `play.py`, with a dependency-free test suite.

```bash
python tests/test_games.py       # 20 checks: headless fuzz, save/load, and
                                 # a regression test for every fixed bug
```

The tests inject a fake `curses` module, so they run on any interpreter with or
without a real curses build. Build the package with `python -m build`.

## Contributing

Issues and pull requests are welcome. Good first additions: a new game (subclass
`Game` and add it to `_GAMES`), an extra Sokoban level, or a new color theme. Please
run `python tests/test_games.py` before opening a PR.

## License

[MIT](LICENSE)
