# Phase 0 Audit: `play.py` (4704 lines, 14 games, v2.6.2)

Scope: `C:/Users/kirti/Music/claude-games/play.py`, plus `tests/test_games.py`, `pyproject.toml`, `README.md`.
Every finding below survived an adversarial verification pass against the real code. 68 additional candidate findings were refuted and dropped.

---

## 1. Executive summary

The repo is in better shape than the complaints suggest, but the complaints are all real, and two of them are worse than reported.

**Complaint 1: "the games are buggy and glitchy." CONFIRMED, and three of them are fundamentally broken.**

- **Frogger is not a game.** `handle_input` (line 3246) mutates the frog position on every buffered keypress while `update()` (line 3282) only collision-checks the single row the frog occupies at tick time. Holding Up walks the frog from the start bank through three road lanes and three river rows into a home bay with zero collision checks. Hold Up four times and you "win" (finding `frogger-1`).
- **Dino has a guaranteed-death obstacle.** The jump apex (`jump_power = -2.0`, `gravity = 0.5`, lines 1078-1079) clears the 5-row XL cactus for exactly 2 of the 9 airborne ticks, but at starting speed the cactus sits in the hit window for 3 ticks. The XL cactus is mathematically unjumpable for roughly the first 17 seconds of every run, and it spawns with 12 percent probability from the first obstacle (line 1155). Verified by brute-forcing all sub-tick launch phases (finding `dino-1`).
- **Space Shooter is unlosable.** Regular enemies never fire (the only `enemy_bullets.append` in the class is line 1550, inside the boss branch), enemies that reach the bottom are silently deleted for free (line 1537), and `_fire()` (line 1468) has no cooldown or bullet cap. Park in a corner, hold Space, live forever (findings `shooter-1`, `shooter-2`).

Plus a class of cross-cutting glitches: the keypress that dismisses the help overlay is also consumed as a game move (base loop lines 461-466 clear `_show_help` *before* line 466 recomputes `active`), which in 2048 spawns a tile and in Reversi commits an irreversible disc (`2048-2`, `reversi-4`). Pausing Tetris while a piece rests on the stack locks that piece instantly on resume, because `last_drop` is raw wall clock that keeps running while the sim is halted (`tetris-5`). Flappy dies on a terminal resize (`flappy-5`).

**Complaint 2: "mis-paced, some too fast to react to, some too slow." CONFIRMED, but the diagnosis is not what you would guess.** There is no input-driven acceleration left in the *world* clock: commit 73a872c genuinely fixed that, and the base loop (lines 442-497) is a correct fixed-timestep wall-clock loop. But **commit 73a872c fixed the world clock and not the player clock.** Five games still move the player inside `handle_input()`, so the paddle/ship/frog moves at the OS key auto-repeat rate, complete with the ~0.5 s auto-repeat start delay: Breakout paddle (1285), Pong paddle (1842), Shooter ship (1459), Frogger frog (3246), Tetris soft drop (777). In Pong on hard the AI paddle moves a guaranteed 75 rows/s every tick while the human paddle is at the mercy of a keyboard setting.

**Complaint 3: "several games feel indistinguishable." CONFIRMED, and section 2 makes it visible.** Seven of the ten real-time games sit inside a single 40-90 ms tick band: Pong 40, Dino 48, Tetris 50, Shooter 50, Flappy 50, Breakout 60, Pac-Man 80, Frogger 90. That is the mechanical cause. Worse, six of them are *flat*: Breakout's ball speed literally never changes (the 4-tier arcade ratchet is absent, `breakout-1`), Shooter's spawn rate and enemy speed are never modified after `setup()` (`shooter-7`).

**Complaint 4: "multiplayer needs verification." VERIFIED. It works, and it is architecturally correct.** LAN host/join genuinely functions end to end for Reversi, Connect Four and Pong. Nobody double-simulates (Pong is host-authoritative, the board games sync moves and recompute passes deterministically). But it is fragile outside a lab: no move acknowledgement (a single lost frame deadlocks the board games permanently), no heartbeat (a pulled cable hangs forever), and pressing `?` freezes the network game for both players because `update()` is the only thing that touches the socket. See section 5.

**One thing that is genuinely good:** rendering. There is exactly one `clear()` in the file (line 3678, outside the menu loop) and zero `refresh()` calls. Every frame is `erase()` + draw + `noutrefresh()` + `doupdate()` (lines 468, 510-511). No flicker, no tearing. Carry it over verbatim.

**Games that are fine:** Sokoban (correct push rule at 2818-2835, correct turn-based pacing, no randomness), 2048 (mechanically faithful; its defects are presentation-only), Snake (canonical move step; its defects are input-buffer depth and a missing win state). Reversi's rules engine and Connect Four's rules engine are both correct.

---

## 2. Pacing table (the "they all feel the same" artifact)

| Game | `get_timeout()` | Line | Ticks/sec | What actually sets the felt pace | Genre demands | Verdict |
|---|---|---|---|---|---|---|
| **Pong** | 40 ms | 1807 | 25 | ball 1.0 -> 2.6 cells/tick (1836, 1982) | 60.05 Hz; 2.13 s -> 1.07 s per exchange | Horizontal envelope roughly right, ramp shape wrong (continuous 5%/hit, not the 2-threshold gate). **Fastest tick in the file.** |
| **Dino** | 48 ms | 1093 | 20.8 | scroll 1.0 -> 2.4 cells/tick (1104) | 60 fps; reaction 1.4 s -> 0.65 s | Reaction window 3.3 s -> 1.4 s, *more generous* than Chrome. Not too fast. Ramp ends at 48 s vs canon 116 s. |
| **Tetris** | 50 ms | 768 | 20 | `drop_interval` 0.80 s -> 0.12 s (724) | L1 1.000 s -> L10 0.064 s -> L15 0.007 s | Tick is only a heartbeat. Felt pace is the drop clock, which flatlines at level 14. **Not** one of the same-feeling games. |
| **Shooter** | 50 ms | 1433 | 20 | ship speed = OS key repeat (1460) | 60 Hz; alive-count rack acceleration | Flat. `spawn_rate`/`enemy_speed` never change after setup (1411-1412). |
| **Flappy** | 50 ms | 2085 | 20 | gravity 0.3, flap -1.5 (2055-2060) | 60 fps, **no difficulty ramp at all** | Tick is fine; uncapped fall reaches 3.5 rows/tick = half a pipe gap per drawn frame (2095). |
| **Breakout** | 60 ms | 1283 | 16.7 | **nothing. Ball is 1.0 row/tick forever** (1245-1246) | 4-tier speed ratchet per serve | **Zero difficulty curve from brick 1 to brick 48.** The dead speed cap at 1324-1328 proves it was intended. |
| **Pac-Man** | 80 ms | 2477 | 12.5 | Pac 1 tile/tick = 12.5 tiles/s | arcade Pac = 7.58 tiles/s | **1.65x arcade speed**, tile-granular. Ghost speed is a 3-step cliff (2426, 2659), not a ramp. |
| **Frogger** | 90 ms | 3237 | 11.1 | lanes 0.30-0.60 cells/tick (3187-3197) | road 2-9 cells/s, river 3-5.6 | Speeds are in band. Frozen forever: no level scaling, `supports_difficulty` left False (279). |
| **Snake** | `max(110, 180 - score*2)` | 607 | 5.6 -> 9.1 | the ramp itself | 167 ms start, 80 ms floor | **Slowest real-time game by a wide margin.** Slightly *too slow* vs canon. Not a culprit. |
| **Minesweeper** | 200 ms | 2275 | 5 | nothing; it is turn-based | no clock in the rules | **Wired into the real-time loop for no reason** other than to drive a frame counter. Repaints a static 480-cell board 50x/sec. |
| **2048** | -1 (blocking) | 961 | n/a | one move per keypress | no clock | Correct. |
| **Sokoban** | -1 (blocking) | 2815 | n/a | one move per keypress | no clock | Correct. The one game paced right. |
| **Reversi** | -1 solo / 120 net | 2955 | n/a | zero latency everywhere | 150-250 ms flip anim + 300-600 ms AI pause | Correct choice, but **0 ms of both.** Board teleports. |
| **Connect Four** | -1 solo / 120 net | 3470 | n/a | zero latency everywhere | 180-260 ms accelerating fall + 200-300 ms AI think | Correct choice, but **0 ms of both.** Human disc and AI disc land in one redraw. |

**The band:** Pong 40, Dino 48, Tetris 50, Shooter 50, Flappy 50, Breakout 60, Pac-Man 80, Frogger 90. Eight games inside 40-90 ms. Snake at 110-180 ms and Minesweeper at 200 ms are the only real-time outliers, and Minesweeper should not be real-time at all.

**The deeper problem is not the tick, it is that the tick is the only knob anyone turned.** Felt pace should come from the avatar's cells-per-second and from the difficulty ramp. Breakout has no ramp (`breakout-1`). Shooter has no ramp (`shooter-7`). Frogger has no ramp (`frogger-3`). Pac-Man's ramp is a 40-second cliff into unavoidable death (`pacman-6`). Tetris's ramp stops at level 14. Flappy has a ramp it is not supposed to have.

---

## 3. Per-game sections

### 3.1 Snake (552-667)

**Canonical:** delayed-tail growth, lenient tail-vacate rule, turn FIFO of depth 2 validated at apply time, explicit board-full win state.

**Status: one of the most faithful implementations in the file.** The move step is canonical: lenient tail-vacate at 632 (`body = self.snake if grow else self.snake[:-1]`), delayed-tail growth at 636-641, wall bounds at 626 exactly matching the food spawner interior at 599-600, food never spawns inside the snake (598), and the reversal guard at 610-618 correctly tests the last *committed* direction, so the "double-tap kills you into your own neck" bug is not present. Pacing (180 ms -> 110 ms, line 607) is the slowest in the file and is if anything slightly slow versus canon.

**Bugs:**
- `snake-1` (medium, 609-621): single `next_direction` slot, no FIFO, and a reversal is *rejected* rather than *queued*. Moving Right, press Up then Left inside one tick: Up is accepted, then `handle_input` re-reads the still-stale `self.direction = (0,1)`, sees `dx == 1`, and **silently discards the Left**. Fast L-turns are impossible. This is the most player-visible defect in Snake.
- `snake-2` (medium, 597-602): `_spawn_food` leaves `self.food` unchanged when the board fills, so a phantom pellet is drawn under the snake's head. `self.won` is never assigned anywhere in the class, so a full-board win can only ever print "GAME OVER".
- `snake-3` (low, 486-497): the base catch-up loop can run 3 `update()`s between rendered frames with one key read. For a cell-stepped game that is 3 unsteerable, unseen moves, which can be an unearned death.

**Multiplayer:** none. Absent from `_NET_GAMES` (3769-3773). No Blockade-style two-player path. Base loop network guards degrade correctly (`getattr(self, 'net', None)` at 459).

---

### 3.2 Tetris (684-866)

**Canonical:** SRS with 5-entry x/y kick tables, 0.5 s Extended Placement lock delay with 15 resets, 7-bag randomizer, 20-row buffer zone, no hard-drop auto-repeat, 7 distinct piece colors.

**Status: competent but heavily simplified.** Gravity is correctly decoupled from input, spawn columns happen to match the Guideline (690, 726-733), and the Single/Double/Triple/Tetris score table is right.

**Bugs:**
- `tetris-1` (medium, 795-802): **no lock delay at all.** The piece locks on the first gravity tick after touchdown. Soft drop (777-780) does not touch `last_drop`, so the grace window is a uniformly random 0 to `drop_interval` depending on where in the gravity phase you happened to land.
- `tetris-2` (medium, 684-685, 781-787): rotation is a naive bounding-box `zip(*shape[::-1])` with a horizontal-only kick list `[0, -1, 1, -2, 2]`. **No floor kick.** A T or I resting on the surface can never rotate: rotating T needs `cur_y+2`, `_hit` rejects at 740, and no `dx` can fix a vertical overflow. T-Spin Triple is mathematically impossible.
- `tetris-3` (medium, 711, 728): `random.choice(list(_SHAPES))`, not the 7-bag. A 20-piece I-drought has a 4.6% chance and will happen roughly every 20 games.
- `tetris-4` (medium, 788-793): hard drop is bound to a raw `ord(' ')` with no edge detection and no ARE. **Holding Space chain-hard-drops every new piece and tops you out in a couple of seconds.**
- `tetris-5` (medium, 706, 713, 796-802): `last_drop` is `time.time()` and keeps running while the sim is halted. **Pausing (or opening `?`) with a piece resting on the stack locks that piece instantly on resume.**
- `tetris-7` (low, 681): `_PIECE_COLORS` maps O and L both to pair 3 (YELLOW). Under `retro` the Z/T collide; under `ocean` S/T and I/J collide.
- `tetris-11` (low, 690, 726-733): flat 20x10 board, no buffer zone, so there is no Lock Out condition and the top two rows are permanently unusable.

**Multiplayer:** none. Single-player only, no dead net code.

---

### 3.3 2048 (871-1033)

**Canonical:** 10% four spawn, spawn only on a real move, spawn before the game-over test, merge-toward-the-wall pairing, no re-merge in one move.

**Status: mechanically remarkably faithful, and correctly turn-based.** `get_timeout()` returns -1 (961-962), one move per keypress (498-499), no cooldown, no input lock. Spawn is 10% four (898) uniform over empty cells (897), fires only on a change (940-943), and happens before the game-over test (943, 969) exactly as canon requires. `_slide` (900-912) pairs correctly ([2,2,2] left -> [4,2,0,0]) and a merged tile cannot re-merge. Scoring is the new tile value (905-907). `_can_move` (950-959) is the exact predicate.

**Bugs:**
- `2048-1` (medium, 944-947, 515-520): `self.won` is a sticky flag that is never cleared, and `_game_over_screen` has only two branches. **Reach 2048, keep playing, then fill the board and die: the game prints "YOU WIN!"** The flag is persisted (891), so a resumed save keeps the mislabel.
- `2048-2` (medium, 461-466, 483-484): line 464 clears `_show_help` before line 466 recomputes `active`, so **the direction key you press to close the help overlay also slides the board and spawns a tile.** In 2048 an unintended slide can permanently ruin a corner build.
- `2048-5` (low, 501-503, 513-537): the game-over text is painted over the grid with no erase, shredding the box-drawing borders of the final board.

**Multiplayer:** none, and none expected. Canonical 2048 has no multiplayer either.

---

### 3.4 Dino (1038-1197)

**Canonical:** every obstacle clearable with a normally-timed jump; difficulty comes from reaction time collapsing (1.4 s -> 0.65 s), never from an unclearable obstacle. Launch velocity scales with speed. Second axis: pterodactyls + duck.

**Status: pacing is fine, geometry is broken.** 48 ms tick, scroll ramp 1.0 -> 2.4, giving a 3.3 s reaction window at start and 1.4 s at cap, which is *more* generous than Chrome.

**Bugs:**
- `dino-1` (**HIGH**, 1078-1079, 1104, 1129, 1136-1149, 1155): **the XL cactus is mathematically unjumpable at starting speed.** Simulating the exact integrator at 1107-1113 gives `int(dino_y) = [-2,-3,-4,-5,-5,-4,-3,-2,0]`. The height test at 1147 reduces to "collide unless `int(dino_y) <= -oh`", and `_CACTUS_XL` (1046) is 5 rows tall, so there are exactly 2 safe ticks. The horizontal hit test at 1146 is true for `int(obs['x'])` in {8,9,10}, and at speed 1.0 the obstacle steps one column per tick, so it occupies that window for exactly 3 consecutive ticks. Three danger ticks cannot fit inside a two-tick apex for any launch timing. Speed only reaches 1.5 at score 120 (about 17 s in) while line 1155 can roll `xl` on the very first spawn (about 1.4 s in). Guaranteed death, 12% of early spawns.
- `dino-3` (medium, 1186-1188): the ground parallax dots scroll **RIGHT** (`off = int(self.frame * self.speed) % 6` walks upward) while obstacles scroll LEFT (1116). It reads as the dino running backwards.
- `dino-8` (low, 291-295, 1117, 1179-1183): `safe_addstr` bails entirely on `x < 0` instead of clipping, so a cactus vanishes in one frame the moment its left edge hits column -1, with 2 of its 3 columns still on screen.

**Multiplayer:** none, and canon has none.

---

### 3.5 Breakout (1202-1393)

**Canonical:** 4-tier ball-speed ratchet per serve (volley 4, volley 12, orange/red brick latch), paddle halves on top-wall contact for the rest of that ball, 4-zone deterministic deflection, 8x14 wall scoring 1/3/5/7, second wall refill.

**Status: a competent Arkanoid clone that is not Breakout.**

**Bugs:**
- `breakout-1` (medium, 1245-1246, 1297-1298, 1313, 1319, 1343): **the entire speed ratchet is missing.** `ball_dy`'s magnitude is permanently 1.0: it is only ever passed through `abs()` or negated. There is no volley counter, no brick latch, no state at all tracking paddle hits. Combined with a flat 60 ms tick, the ball travels 16.67 rows/sec identically on brick 1 and brick 48. **Zero difficulty curve.**
- `breakout-2` (medium, 1285-1294): the paddle moves 3 columns **per key event**, not per tick. Paddle velocity is the OS auto-repeat rate. Three consequences: the ~0.5 s auto-repeat start delay the canon spec forbids; queued keys keep the paddle sliding after release; alternately mashing A and D is faster than holding either.
- `breakout-3` (medium, 1239, 1312-1314): **paddle never halves on top-wall contact.** `paddle_w` is set to 8 at 1239 and never reassigned. Opening a tunnel is pure upside; the endgame has no teeth.
- `breakout-6` (low, 1324-1328): the ball speed cap is **dead code**, unreachable on every possible input (max `spd` is 1.414, the test is `> 2.0`). A tell that speed variation was intended and never implemented.

**Multiplayer:** none. No dead net code path.

---

### 3.6 Space Shooter (1394-1741)

**Canonical (Space Invaders / Galaga):** one player shot on screen (two for Galaga); fire rate gated by *accuracy*, not a timer; up to 3 alien shots, one of them aimed; rack speed = f(alive count); shields; UFO.

**Status: not a Space Invaders clone in any structural sense.** A random top-down spawner with 4 enemy types, powerups, and a boss every 5 waves.

**Bugs:**
- `shooter-1` (**HIGH**, 1465-1473): **unlimited autofire.** `_fire()` appends unconditionally: no bullet cap, no cooldown, no fire timer anywhere in the class. `handle_input` runs on every 20 ms poll (443), so a held or mashed Space emits up to 50-150 bullets/sec against a 20 Hz sim. Deletes the entire aiming-and-tempo economy the genre is built on.
- `shooter-2` (medium, 1540-1550): **regular enemies never fire a single shot.** The only `enemy_bullets.append` in the class is line 1550, inside the boss branch, and bosses only spawn on `wave % 5 == 0` (1664). Waves 1-4, 6-9, 11-14 contain zero incoming projectiles.
- `shooter-7` (medium, 1475-1485, 1652-1665, 1411-1412): no formation, therefore no emergent alive-count acceleration. `spawn_rate` and `enemy_speed` are set once at setup and **never reassigned**. Only `kills_needed` grows (1662), so late waves are *longer*, not harder.
- `shooter-5` (low, 1514-1517): player bullet and enemy bullet both move 1 cell/tick. Canon demands 3:1.
- `shooter-12` (low, 1403-1408): `setup()` blindly `setattr`s every key from the save with no clamping against the current `self.w`/`self.h`. A save from a 120-column terminal resumed in a 60-column one puts the ship off-screen. The early `return` at 1408 also means difficulty values come from the save, not from the picker the player just used.
- `shooter-13` (low, 1735-1740): at `min_w = 40` the powerup status (columns 2-20) and the control footer (starting at `w - 28` = 12) **overlap**.

Combined with enemies reaching the bottom being deleted for free (1537, no life loss), a player who parks in a corner and holds Space is effectively immortal.

**Multiplayer:** none, and no local 2P either.

---

### 3.7 Pong (1745-2046)

**Canonical:** 8 quantized deflection zones with a double-wide flat center; a gap at top and bottom so the paddle cannot cover the field; the ball is served *toward* the player who missed, retaining its velocity; 2-threshold / 3-step acceleration.

**Status: physics core is structurally sound** (paddle bounce is an assign not a negate, so no in-paddle trapping; wall bounce preserves |vy|; speed resets on every point).

**Bugs:**
- Paddle movement is key-event driven (1851-1853, 2 cells per keypress) while the AI paddle moves a guaranteed 1/2/3 cells **every tick** (1973/1976). On hard the AI moves 75 rows/s and the human physically cannot match it during the first half-second of a press (this is the cross-cutting `handle_input` issue, listed in section 4 and in the priority table).
- `pong-5` (low, 1946-1957, 1833-1840): **serve direction is inverted.** When the human (left) misses, `server` becomes `'player'` and `dx` becomes `+1.0`: the ball is launched *away* from the player who just lost the point. The vertical velocity at the miss is also thrown away for a coin flip.
- `pong-8` (medium, 1758-1762, 1901, 1946-1957): solo mode derives the playfield from the live terminal size every tick. **Shrinking the terminal instantly gifts points** (ball at x=70 on an 80-col terminal, drag to 60 cols, and `elif self.ball_x >= pw - 2` fires) and strands the paddles outside the field. Net mode already does this right with a fixed 60x20 logical field (1755-1756).

**Multiplayer: YES, and it works.** See section 5.

---

### 3.8 Flappy Bird (2050-2170)

**Canonical:** the flap ASSIGNS velocity (correct here, line 2089); **there is no difficulty ramp**; the ceiling is solid but harmless; fall speed is clamped to roughly the flap magnitude; a Get Ready state; a nose-down death fall; medals.

**Status: the one rule that matters most is right, everything else drifts.**

**Bugs:**
- `flappy-3` (**HIGH**, 2087-2089, 2099): **holding W or Space is a guaranteed self-kill.** Auto-repeat delivers ~25-30 chars/s, faster than the 20 Hz physics tick, so `bird_vel` is re-assigned to -1.5 before gravity can eat it. The bird climbs at a locked 30 rows/s into the lethal ceiling with no counterplay.
- `flappy-2` (medium, 2098-2101): the ceiling is lethal. Canon says it is a solid but harmless wall and there are exactly two lethal surfaces, not three.
- `flappy-4` (medium, 2095-2096): **no terminal-velocity clamp.** A full-height dive reaches 3.46 rows/tick = 69 rows/s, 2.3x the climb speed, and at 20 FPS the bird moves half a pipe gap (`PIPE_GAP = 7`) between drawn frames. It reads as a teleport, not a fall.
- `flappy-5` (medium, 2098-2100, 452, 471-479): **a terminal resize kills the bird.** `ground_y = self.h - 2` moves under the sim; a bird at row 24 in a 30-row terminal dies the instant you shrink to 24 rows. `setup()` already knows about this hazard and guards it at 2072-2074; `update()` does not.
- `flappy-6` (low, 2105-2107), `flappy-9` (low, 2076-2082), `flappy-10` (low, 2099-2101), `flappy-11` (low, 2163-2164): no 20% gap margin band, no Get Ready state (the bird falls on tick 1 before you touch anything), no death sequence, no medals. The stats line advertises the non-canonical speed multiplier.

Also: line 2093 ramps scroll speed 1.0 -> 2.2 with score and line 2109 shrinks the pipe cadence. **Flappy Bird's defining design decision is that there is no difficulty ramp.**

**Multiplayer:** none, and canon has none.

---

### 3.9 Minesweeper (2174-2359)

**Canonical:** first click is a guaranteed zero; chording is the entire speed game; the timer is a wall clock armed on the release of the first click, capped at 999; per-level high scores by *time*.

**Status: core model is sound.** Mines are placed after the first click with a full 3x3 exclusion (2217-2226), the cascade stops at flags (2244), the win condition counts revealed non-mine cells rather than flags (2267-2272), and flagging is unrestricted so the counter can go negative, which is canon.

**Bugs:**
- `mines-1` (low, 2277-2291, 2256-2258): **chording is entirely absent.** `handle_input` has only move/reveal/flag, and `_reveal_cell` returns immediately on an already-revealed cell. Every number must be opened cell by cell; a 30x16 Expert board becomes a grind.
- `mines-2` (low, 2293-2295, 2306): the timer is fake. `elapsed = self.frame // 5`, and `frame` starts at new-game rather than at the first reveal, is stopped by pause, is stopped by shrinking the terminal (the size gate `continue`s at 479), and silently drops time under any stall (the 3-step catch-up cap at 490-497).
- `mines-4` (low, 2262-2265, 2318-2333): no red detonated mine, no X over wrong flags, no auto-flag on win.
- `mines-5` (low, 2249, 2199-2200): high score is a saturating *cell count* on a single cross-difficulty key. One hard win writes 381 and easy/medium can never register again.
- `mines-7` (low, 2214, 2336-2339): the 49-char control hint is truncated at the declared `min_w = 40`.

**Pacing:** this is a turn-based game wired into the real-time loop (`get_timeout()` 200, line 2275) purely to drive a frame counter, repainting a static 480-cell board 50x/sec. Its two sibling turn-based games correctly return -1.

**Multiplayer:** none.

---

### 3.10 Pac-Man (2363-2739)

**Canonical:** a global scatter/chase timer that all four ghosts obey (7/20/7/20/5/20/5/forever on L1), forced reversal on every mode change; four *distinct* deterministic AIs including Inky's Blinky-vector target; frightened ghosts slow to 50%; 200/400/800/1600 ghost chain; level progression; bonus fruit; extra life at 10,000.

**Status: a tile-hop maze chase, not Pac-Man.**

**Bugs:**
- `pacman-1` (**HIGH**, 2493-2580, 2597-2660): **no scatter/chase timer exists at all.** A grep for "scatter" over the whole file returns zero hits. The ghosts chase relentlessly from frame 1 and the game never breathes. The only reversal in the game is the energizer reversal at 2634-2636.
- `pacman-3` (**HIGH**, 2396, 2533-2548): **Inky is a pure random walker** (`('Inky', 4, 'random')`). He has no target, no reference to Blinky, no reference to Pac-Man. His apparent erraticness must *emerge* from Blinky's live position. A random Inky is worse than a duplicate ghost: he is unreadable AND unfair.
- `pacman-4` (medium, 2662-2674): ghost-eating is a flat 200. No 200/400/800/1600 chain, no multiplier state anywhere in the class.
- `pacman-6` (medium, 2499-2515, 2653-2655): frightened ghosts do not slow down, and fright lasts 2.4 s (2633) versus canon's 6 s on L1. Combined with `ghost_speed` dropping to 1 at 38.4 s (2659), late-game fright means eating a ghost that moves at exactly your speed, randomly. Mostly luck.
- `pacman-9` (medium, 2499-2515, 2533-2548): frightened ghosts and random-Inky **ignore the ghost door** and can hide in the pen, where Pac-Man cannot follow. Effectively un-eatable for the rest of the fright window.
- `pacman-10` (medium, 2638-2641): **winning ends the game.** Clearing the maze sets `game_over = True`. There is no `self.level` anywhere in the class, so the entire difficulty ramp the game is famous for never happens.
- `pacman-11` (medium, 2502, 2535): ghost AI is seeded from the global RNG. The game is nondeterministic and cannot be patterned. Canon reseeds identically on every life and level.
- `pacman-16` (low, 2622-2636, 2662-2674): no bonus fruit, no extra life at 10,000.

**Pacing:** Pac-Man moves a full tile every 80 ms tick = **12.5 tiles/s, 1.65x arcade speed**, on a maze only 27 wide, so you cross it in about 2 seconds. Ghosts go from 33% of your speed to exactly 100% of it in 38 seconds via three discrete steps (2426, 2659-2660). That is a cliff, not a ramp: trivially safe to unavoidable head-on death, then flat forever. `ghost_speed` is also never restored on death.

**Multiplayer:** none.

---

### 3.11 Sokoban (2743-2908)

**Canonical:** push only, never pull; a push is legal iff the cell beyond the box is free; illegal moves are silent no-ops; exact undo.

**Status: correct where it matters most, and the one game paced right.** The push rule at 2818-2835 is exactly canonical (`if (by, bx) in self.walls or (by, bx) in self.boxes: return`), boxes never move by any other means, a push increments both `moves` and `pushes` while a plain step increments only `moves`, illegal moves are silent no-ops with no history entry. `get_timeout()` returns -1 (2815), so it blocks on getch and steps exactly one grid cell per keypress. No randomness, so determinism and exact undo hold. All glyphs are ASCII (`#$*.@+`), so no Windows wide-char problems. Box-on-goal is correctly distinguished (`ch = '*' if on else '$'`, 2884).

**Bugs:**
- `sokoban-3` (low, 483-503, 2855-2865): **the solved board is never rendered.** `update()` calls `_start_level(self.level_idx)` before `draw()` runs, so the completion frame (all boxes as `*`), which is the entire payoff of a Sokoban level, is never shown. On the final level `draw()` runs but line 502-503 returns to the game-over screen before the `doupdate()` at 510-511, so that frame is never flushed either.

Also noted: `_move` has no grid bounds check at all and relies entirely on the levels being perfectly wall-enclosed, and R resets the board but not the counters.

**Multiplayer:** none, and canon has none.

---

### 3.12 Reversi (2912-3177)

**Canonical:** fixed diagonal start, black first, no gap-jumping, no cascade chaining, double-pass terminal, **passes must be visible**, 32-32 is a draw, exact endgame solve.

**Status: the rules engine is correct.** The opening position (2947-2948) matches the WOF/USOA start exactly, `_flips` (2957-2968) brackets properly, illegal placements are a no-op, and the double-pass terminal check (3092-3094) is genuinely correct including wipeouts. The AI uses the real Norvig PAIP weighted-square table verbatim (2919-2928) and measures 3-5 ms per move, so there is no freeze.

**Bugs:**
- `reversi-4` (**HIGH**, 461-466, 483-484): **the keypress that dismisses the help overlay is consumed as a move.** The help text itself says "Space/Enter: Place disc", so a user who opens help and taps Space to close it **commits an irreversible disc** at the cursor.
- `reversi-1` (medium, 3097-3121): the player's own pass message ("No move - you pass", line 3101) is assigned and then **unconditionally overwritten at line 3120 before a single frame is rendered.** It is dead code. The player never learns they passed; the board just changes twice in one turn.
- `reversi-2` (low, 3104-3107): the AI's pass sets no message at all. The human is handed two turns in a row with no explanation. Canon calls the pass "the single most-botched rule and it must be visible".
- `reversi-3` (medium, 3056-3121, 483-501): **zero flip animation and zero AI thinking pause.** The human's disc, its flips, the AI's disc and its flips all land in one single frame. A 12-disc swing is an instantaneous state teleport, which destroys the outflank rule's legibility.
- `reversi-11` (medium, 3013-3025, 3041): negamax evaluates the horizon *before* checking for a terminal node, and burns a ply on every pass. The advertised "deeper endgame search" (depth 5 against up to 10 remaining plies) cannot see the final disc count.
- `reversi-9` (low, 3051-3054): a 32-32 draw is presented as red "GAME OVER". Perfect play is a draw (Takizawa 2023), so this shows a strong player their target result as a defeat.
- `reversi-6` (low, 3079-3083), `reversi-7` (medium, 3079, 3097-3112): net disconnect bugs, see section 5.
- `reversi-5` (low, 2915, 3161): the 40-char hint is truncated at `min_w = 34`, losing `ESC:Quit`.

**Multiplayer: YES.** See section 5.

---

### 3.13 Frogger (3181-3373)

**Canonical:** discrete grid stepper, one deflection = exactly one hop, at most one input buffered during a hop; a 30-second clock per frog that kills you and pays a time bonus; five bays; level progression; turtles that dive, a fly, a lady frog, gators.

**Status: the traffic pacing is defensible (3.3-6.7 cells/sec), and then the game is invalidated by its input model.**

**Bugs:**
- `frogger-1` (**HIGH**, 3246-3257, 3282-3318, 483-497): **unlimited hops per tick.** `handle_input` mutates `frog_row`/`frog_x` immediately on every buffered keypress, while `update()` only evaluates the ONE row the frog occupies at tick time. Rows passed *through* between two ticks are never tested. The frog starts at row 8 and home is row 0, so 8 buffered `w` presses inside one 90 ms window carry the frog from the start bank into a home bay through 3 road lanes and 3 river rows **without a single collision or drowning check**, scoring the full 8 forward-hop points plus 50 for the home. Repeat four times and the game is won without risk. The same hole lets you dodge an incoming car with two lateral hops inside one tick. **This single defect invalidates the entire game.**
- `frogger-2` (medium, 3214-3237, 3282-3318): **there is no timer at all.** No timer field exists in the class. `self.frame` is written and serialized but never read by any logic. The 30-second clock is Frogger's actual antagonist and the reason you commit to a gap instead of waiting for a safe one.
- `frogger-3` (medium, 3266-3280, 3187-3197, 279): no level progression. Filling the 4 bays ends the game with a 200-point bonus instead of scoring 1000 and starting a harder level. `_LANES` is a class constant that is never copied or scaled, so lane speeds are frozen for the entire game. `supports_difficulty` is left at the base default False (279), so the Easy/Medium/Hard picker is skipped and `self.difficulty` is never read.
- `frogger-4` (low, 3220-3228, 3239-3244): river spawner wrap off-by-one. `FIELD_W = 40`, `gap = 9`, `width = 5`: logs land at 0/9/18/27/36, and the log at 36 wraps to cover column 0, which the log at 0 also covers. **Two logs fuse into a permanent 9-cell mega-platform** that never breaks apart, in all three river rows.
- `frogger-5` (low, 3187-3197, 3239-3240): the river is one homogeneous 5-wide log type. No turtles, no diving, no fly, no lady frog, no gators, no snakes. The road is equally uniform (every vehicle is a 3-wide `[o]`).
- `frogger-10` (low, 3310-3312, 3259-3264): on the final life, an edge death leaves the frog drawn one column outside the field.

**Multiplayer:** none. Canon Frogger is two-player alternating; that is absent.

---

### 3.14 Connect Four (3446-3591)

**Canonical:** 7x6, gravity drop, 69 win windows, number keys 1-7 for instant commit, an accelerating ~204 ms disc fall, a 200-800 ms AI think delay, the last disc distinguished, the winning four highlighted.

**Status: the rules engine is CORRECT.** 7x6 (3450), bottom-up gravity scan (3472-3477), full-column rejection (3480-3481), win-before-draw ordering (3484-3491), strict alternation (3493). The win scanner covers exactly the canonical 69 windows (4298-4320) and the alpha-beta AI does take immediate wins and block immediate losses (verified by running it). Local play blocks on getch, so there is no acceleration.

**Bugs:**
- `c4-1` (**HIGH**, 3479-3527): **no drop animation and no AI think delay.** `handle_input` drops the human disc, then the *same* loop iteration runs `update()` -> `_cli_c4_ai_move` (measured 64-110 ms) -> AI disc, and only then does `draw()` run once. Both discs materialize in a single redraw. Proof this is unintentional: the string `'AI is thinking...'` at line 3577 is **literally unreachable dead code**, because `self.turn` is never 2 at draw time.
- `c4-2` (medium, 3529-3558): **the game-over banner is stamped through the middle of the board.** On a standard 80x24 terminal the board disc rows are 7/9/11/13/15/17 and the banner rows are 9, 11 and 15. The player cannot see the winning four that just ended the game.
- `c4-7` (medium, 3572-3577): the LAN guest is player 2 and draws as `O`, but `return 'Your turn (X)'` hardcodes `(X)`. **The guest is told they are X for the entire game.** ReversiGame gets this right at 3132-3133, so the fix pattern already exists in the file.
- `c4-4` (low, 3496-3507): **number keys 1-7 are not accepted**, even though the board prints 1-7 column labels at 3542 and the CLI variant accepts them (4439). 84 keystrokes where 21 would do.
- `c4-5` (low, 3503-3507, 3537-3542): dropping into a full column is a completely silent no-op (no beep, no message), and the hover ghost `v` is still drawn over full columns.
- `c4-6` (low, 3548-3554): the last placed disc is not distinguished and the winning four is not highlighted. `_do_move` throws away the landing row that `_drop` already returns. The CLI variant *does* track this (4294, 4449), so the curses game is the regression.
- `c4-8` (low, 3509-3523), `c4-9` (low, 3448-3449, 3564-3567): net disconnect blind spot, and the control hint is drawn off-screen at the declared `min_h = 18`.

**Multiplayer: YES.** See section 5.

---

## 4. Shared infrastructure

### 4.1 What is sound and must be carried over verbatim

- **Rendering.** Exactly one `clear()` (3678, outside the menu loop), zero `refresh()` calls, every frame is `erase()` (468) + draws + `noutrefresh()`/`doupdate()` (510-511). All writes route through the bounds-checked `safe_addstr` (291) or its menu twin `_safe` (3637). No game bypasses them. No flicker, no tearing.
- **The tick accumulator itself** (442-497): a correct fixed-timestep wall-clock loop on `time.monotonic()`, re-reading the interval every frame (487) so Snake's score ramp works without drift, capped at 3 catch-up steps with a stall resync (496-497).
- **The too-small-terminal gate** (471-479): renders a message, skips `update()`, resyncs `next_tick` so no time is banked, and leaves `q`/ESC working (the quit check is at 454, before the gate).
- **The color fallback chain** (239-270): `_HAS_CURSES` guard, `start_color()` in try/except, `has_colors()` check, `use_default_colors()` with a `COLOR_BLACK` fallback, each `init_pair` individually try/excepted. Never asks for more than 8 colors, so there is no 256-color fallback problem by construction.
- **Save formats.** Everything is JSON keyed by the class `name` attribute. Nothing is pickled, so no class path is embedded and a module split cannot corrupt saves, *provided the `name` strings are left alone*.

### 4.2 What is tangled and must be fixed during extraction

| # | Problem | Lines |
|---|---|---|
| 1 | **Residual input-rate coupling.** `update()` is clock-gated, but five games mutate state inside `handle_input()`, which is called once per `getch()`. Player speed = OS key repeat rate. There is no per-tick input coalescing and no per-tick action budget. | Breakout 1285, Pong 1842, Shooter 1459 + `_fire` 1468, Frogger 3246, Tetris 777/788 |
| 2 | **`KEY_RESIZE` is never referenced anywhere in the file.** It falls through as a plain key: it closes the help overlay (463), is passed to `handle_input` (483), and **triggers a free `update()` in turn-based games** (498). A window resize counts as a game turn in 2048, Sokoban, solo Reversi and solo Connect Four. `curses.resize_term` is never called, which on windows-curses means `getmaxyx()` keeps returning the stale size. | 410, 454-464, 483, 498 |
| 3 | **`_fit_bounds` is never re-run on resize.** Written three times (Snake 585, Breakout 1264, Minesweeper 2211), called only from `setup()`. Shrink above `min_h`/`min_w` and the board is larger than the screen: `safe_addstr` clips it, but collision logic still uses the old bounds. Snake re-centers the origin every draw (643-645), which makes it worse: the board slides under the viewport. | 585, 1264, 2211 |
| 4 | **All JSON writes are non-atomic and racy.** `write_text` with no tempfile+replace, across multiple `play` processes that `_open_in_terminal` actively encourages. | 187, 232, 395, 4517 |
| 5 | **Tetris keeps a second, non-monotonic clock** (`time.time()` vs `drop_interval`) parallel to the base tick. The one game that did not migrate to the base pacing model. A clock step backwards stalls gravity. | 795-803, 722 |
| 6 | **`run()`'s bare `except Exception` around `setup()`** re-`__init__`s and retries, silently swallowing genuine bugs in every game's `setup()`, not just save-schema mismatches. Presents to the user as "my save vanished". | 424-433 |
| 7 | **`_load_save` consumes the file** (`f.unlink()` on read), so a crash right after resume loses the save. | 397-402 |
| 8 | **Networked pause suppression is hardcoded into the base loop** (`not getattr(self, 'net', None)`), leaking game-specific concerns into the core. `net`/`role`/`local_player` are poked onto instances after construction by `_net_menu` (3960-3964) and each of the three net games re-bootstraps them with `getattr`. | 459; Pong 1773, Reversi 2933, C4 3452 |
| 9 | **`ConnectFourGame` (curses) calls the CLI-layer functions.** `_cli_c4_ai_move` at 3527 and the `_c4_*` helpers at 4286-4497: a forward reference that only works because it resolves at call time. | 3527, 4286-4497 |
| 10 | **Duplication.** `_safe` (3637) is `Game.safe_addstr` (291) written twice. Five games keep a private `self.frame` tick counter (Minesweeper 2293, Shooter 1504, Flappy 2091, Frogger, Pac-Man); a base-class `self.ticks` removes all five. | |
| 11 | **`GAME_STATE_FILE` is a single global slot** shared by all four CLI games; `_save_game_state` overwrites unconditionally, so `play cli start 2048` destroys an in-progress CLI snake. The one genuinely shared-and-bleeding piece of state. | 156, 4515 |
| 12 | **Flappy (2128) and Pac-Man (2682) call `load_high_score()` inside `draw()`**, which does `json.loads(read_text())`. At ~50 fps that is 50 JSON file reads per second for the entire session. Dino does it correctly, caching in `setup()` (1059). | 2128, 2682 |
| 13 | **`_open_in_terminal` fails silently on headless Linux.** The gnome-terminal/xterm/konsole fallbacks (112-121) `Popen` with stderr to DEVNULL and `return True` even with no `$DISPLAY`, so the user is told "Opened game in a new terminal window" and nothing happens. Line 119 also interpolates `play_bin` into a double-quoted `bash -lc` string: a path with a space, `"` or `$` breaks or injects. | 67-122 |
| 14 | **No `SIGTERM`/`atexit` handler and no `curs_set(1)` in a finally.** `main()` has no top-level `try`, so Ctrl-C during any game dumps a traceback. `curses.wrapper` does restore the terminal on exception, so this is cosmetic, not fatal. | 125-149, 4628-4700 |
| 15 | **The test suite has no network test at all**, despite README line 164-165 claiming one. `_net_menu`, `_net_handshake`, `NET_PROTOCOL`, `_net_host_wait`, `_net_join_connect` are entirely uncovered. That README line is currently false. `main()`, argv parsing, `_GAME_MAP` aliasing and `_curses_wrapper` are also untested. | tests/test_games.py |

### 4.3 Rename / split footguns (flag loudly)

- **`_migrate_config()` (159-166) only knows about `claude-games`.** Any further rename must migrate from **both** `claude-games` and `terminal-games`, in that order of preference, or every user who installed 2.6.x loses their high scores and in-progress saves. A naive edit of line 161 strands them.
- **`pyproject.toml` line 41 `py-modules = ["play"]`** must become a packages declaration. Setuptools will happily build a wheel that works from the repo root and fails on install.
- **`pyproject.toml` line 44 `version = {attr = "play.__version__"}`** imports the package at build time. Move `__version__` (play.py line 46, currently `'2.6.2'`) to a leaf `_version.py` so a submodule's bare `import curses` cannot break `pip install` on Windows.
- **`play = "play:main"` (pyproject line 38)** must be retargeted, and `main()` prints `__doc__` (4686), so moving `main()` silently changes what `play help` prints.
- **The tests monkeypatch `play.CONFIG_DIR` / `SCORES_FILE` / `GAME_STATE_FILE` (test lines 47-49) and `play.time` (line 436).** If a split does `from .config import CONFIG_DIR`, the name binds at import time in the importing namespace and the monkeypatch becomes a no-op. **The tests would then write into the user's real `~/.config/terminal-games/` and clobber real saves and high scores.** Route through module-qualified access or a settings object.
- **`_TITLE` (3618-3622) still spells "CLAUDE GAMES"** in ASCII art, and `_cli_mode` prints `'CLAUDE GAMES'` at 4532. `shutil.which('play')` at line 71 hardcodes the console-script name.
- **Save keys are the `name` class attributes** (`snake`, `tetris`, `2048`, `dino`, `breakout`, `shooter`, `pong`, `flappy`, `minesweeper_i`, `pacman`, `sokoban`, `reversi`, `frogger`, `connect4`). Changing any of them during the reshuffle silently orphans that game's save and high score.

### 4.4 Proposed module layout

```
termgames/
  __main__.py            <- main() (4626-4701), docstring, __version__ via _version.py
  core/
    config.py            <- 151-187, 4508-4517. ADD _atomic_write_json, route all 5 writers through it.
                            EXTEND _migrate_config to a legacy-name chain.
    theme.py             <- 190-270. Replace the _current_theme global with an accessor.
    render.py            <- 291-312 + 3637-3643. One safe_addstr. Delete _safe. Add a Frame
                            context manager owning erase/noutrefresh/doupdate.
    loop.py              <- 419-511. FIX WHILE EXTRACTING: coalesce input per tick, add an
                            action budget, handle KEY_RESIZE explicitly and route it to a new
                            on_resize() hook, stop calling update() on unmapped keys in
                            turn-based mode, hoist the net pause special-case to a `pausable` flag.
    game.py              <- 275-418, 513-547. The Game ABC + on_resize() + self.ticks.
                            Narrow the bare except around setup() to the save-schema path only.
    terminal.py          <- 67-149. Add curs_set(1) in a finally, a SIGTERM handler, a
                            DISPLAY/WAYLAND_DISPLAY check, and fix the xterm/konsole quoting.
    net.py               <- 3377-3441 + 3769-3974. _NetLink, lobby, plus a NetGame mixin owning
                            net/role/local_player. ADD TCP_NODELAY, heartbeat, move acks.
    registry.py          <- 3595-3635 + 3646-3666. Decorator registration, not a hand-edited list.
    menu.py              <- 3669-3764
    logic/               <- curses-free rules and AI shared by both front-ends.
      connect4.py        <- 4286-4497 (kills the ConnectFourGame -> _cli_* back-dependency)
      reversi.py         <- the pure parts: _flips 2957, _valid_moves 2970, _evaluate 2990,
                            _negamax 3013
      snake.py, g2048.py, minesweeper.py  <- from 3979-4283
  cli/                   <- 4498-4624, importing core/logic
  games/
    snake.py 552-668      tetris.py 672-867      g2048.py 871-1034
    dino.py 1038-1198     breakout.py 1202-1390  shooter.py 1394-1741
    pong.py 1745-2046     flappy.py 2050-2170    minesweeper.py 2174-2359
    pacman.py 2363-2739   sokoban.py 2743-2908   reversi.py 2912-3177
    frogger.py 3181-3373  connect4.py 3446-3591
```

---

## 5. Multiplayer verdict

**The LAN path is real, not a facade. It genuinely works end to end on a quiet LAN for all three games.** Menu key `M` (3755) or `play mp` (4683). Host binds 0.0.0.0:8765 with a 0.25 s accept timeout and an ESC poll (3882-3918), closing the listener before the handshake so a second joiner cannot sneak in (3914). Join uses `create_connection` with a 6 s timeout (3921-3937). Both sides exchange `{'type':'hello','proto':1,'game':key}` and mismatch is caught and reported (3867-3879). Everything is single-threaded and non-blocking. **There are no threads anywhere in the netplay code**, so there are no races.

**The architecture is correct in the one place most hobby netcode gets it wrong: nobody double-simulates.**

| Game | Model | Works? |
|---|---|---|
| **Reversi** | Move sync. Sends `{'type':'place','r','c'}` (3072-3073); the receiver recomputes flips from its own `_valid_moves` and validates with `if (r,c) not in curv: return` (3114-3116). **Passes are not transmitted**, they are recomputed locally (3105-3107). Board state is a pure function of the move list, so it cannot desync. | Yes, with 2 bugs |
| **Connect Four** | Move sync. Sends `{'type':'drop','col'}` (3507); the receiver replays through the identical `_do_move` with an isinstance/range check (3522) and a second full-column check inside `_do_move` (3480-3481). | Yes, with 2 bugs |
| **Pong** | **Host-authoritative state sync.** Host runs all physics and sends `_state()` (1857-1861) every 40 ms tick. The guest sends only `{'type':'p','y'}` (1891) and **does not simulate at all** (1869-1883). No `ball_dx`/`ball_dy` on the wire, so the guest structurally cannot diverge. Physics runs on a fixed 60x20 logical field (1755-1756) so both terminals agree regardless of window size. | Yes, with 3 bugs |

Input is validated: `_num()` rejects NaN/Inf/junk (1863-1867), `_apply_state` clamps everything, Reversi rejects moves not in `curv`, C4 range-checks `col`. A hostile peer cannot easily corrupt state. Saves are correctly disabled in net mode in all three `setup()`s (1775, 2935, 3455) and `get_save_data()` returns None (1817, 3173, 3587). Pause is correctly disabled for net games (459-460).

**But it is fragile outside a lab:**

| Failure | Reality | Lines |
|---|---|---|
| **Lost move = permanent deadlock** | No ack, no sequence number, no resend. `send()` calls `sendall` on a *non-blocking* socket and treats `BlockingIOError` as "drop this frame", but `sendall` may already have written part of the line, so a truncated fragment goes on the wire. Newline framing lets the stream resync, so Pong drops one state frame harmlessly. For Reversi/C4 the move is gone: sender thinks it is the peer's turn, peer thinks it is the sender's. **Both wait forever.** | 3391-3399, 3114-3115 |
| **No heartbeat, no timeout** | `alive` only flips on a clean FIN (`chunk == b''`, 3405-3406) or an `OSError`. Pull the cable and the survivor waits forever. Only ESC escapes. | 3381-3428 |
| **`?` freezes the network game for BOTH players** | `active = not paused and not _show_help and not game_over` (466), and `update()` is the **only** place the socket is polled or written. Pause was correctly excluded for net games (459); the help overlay was not. A host opening `?` stops physics and stops sending. | 466, 490, 499 |
| **Terminal resize freezes the network game** | Same root cause: the size gate `continue`s before `update()`. | 471-479 |
| **Disconnect undetected on your own turn** | `poll()` is only called inside the opponent-turn branch, and `alive` is only mutated inside `poll()`. While it is your turn the socket is never read, so a peer that quits is not noticed until after you commit a move. (`reversi-7`, `c4-8`.) | 3097-3112, 3513-3523 |
| **LAN results pollute the single-player high-score table** | `_game_over_screen` writes `save_high_score` unconditionally, with no `if self.net` guard, unlike `get_save_data()`. Beating a friend counts as beating the AI. | 522-524 |
| **Guest is told the wrong side** | C4 hardcodes `'Your turn (X)'` while the guest draws as O. (`c4-7`.) Reversi's `get_stats()` hardcodes `('You (X)', b), ('AI (O)', w)`, so a guest who won as white reads "You (X): 22, AI (O): 42" and thinks they lost. | 3576, 3168-3170 |
| **Reversi disconnect score is always the BLACK count** | Even when you are white. (`reversi-6`.) | 3080 |
| **Guest can never serve in Pong** | `handle_input` returns at 1849 before reaching the serve branch at 1854. After the guest scores, the match is frozen until the HOST presses SPACE. No serve timer. | 1844-1854 |
| **No `TCP_NODELAY`** | `grep TCP_NODELAY play.py` returns nothing. Both sides write ~110 bytes every 40 ms: exactly the traffic pattern Nagle plus delayed-ACK punishes. **One-line fix, biggest single win for Pong feel.** | 3384-3389 |
| **No interpolation** | The guest snaps to the last received state (1898-1899). Choppy on LAN, visibly stuttering over Wi-Fi. | |
| **Rematch is broken** | `_game_over_screen` returns `'retry'` on `R` (543-545) but `_net_menu` ignores `game.run()`'s return value (3971). Pressing R after a LAN game silently quits to the menu. | 3971 |
| **`SO_REUSEADDR` on Windows** | Line 3884. On Windows this permits binding a port that is *already actively listening*, so two hosts on one box both "succeed" and connections go to an arbitrary one. Windows wants `SO_EXCLUSIVEADDRUSE`. **This repo's user is on Windows.** | 3884 |
| **`_NetLink._buf` is unbounded** | A peer that never sends `\n` grows it forever. | 3408-3414 |

**Local 2-player: none.** Every entry in `_GAMES` (3601-3616) is single-player vs AI, including Connect Four, whose menu description still says "(vs AI)" (3615). `local_player` is only ever assigned by `_net_menu:3963`. There is no hotseat mode. Two people at one terminal cannot play any game in this file.

---

## 6. Terminal rendering verdict

**Flicker: none.** One `clear()` in the file (3678, outside the menu loop). Zero `refresh()` calls. Every frame ends with exactly one `noutrefresh()` + one `doupdate()` (510-511, 538-539, 476-477, 372-373, 3685-3686, 3744-3745, 3783-3784, 3803-3804, 3834-3835). Single window, single update per frame. No tearing. This is correct and should be preserved verbatim.

**Artifacts / trails:** no game leaves sprite trails, because `Game.run` erases centrally at 468. `_draw_help_overlay` correctly blanks its own box first (343-344). **`_game_over_screen` (513-547) is the offender:** it never erases and never calls `draw()`, so it paints "GAME OVER" straight over the last live frame and the Pac-Man maze / Tetris well / Minesweeper grid bleeds through around the text (`2048-5`, `c4-2`). Worse, its wait loop (541-547) never redraws, so **a terminal resize while the game-over screen is up leaves the screen permanently garbled.** Affects all 14 games.

**Bottom-right corner cell:** `safe_addstr` (291-301) clamps only the right edge, which explicitly permits landing on the last column (295: `text[:max(0, w - x)]` allows `x + len(text) == w`), and swallows the resulting `curses.error` (300-301). Pac-Man triggers it today at its own declared minimum (30x24): the 42-char hint at line 2718 lands on cell (23, 29). It does not crash, but it is an unguarded classic. `_safe` (3637) has the identical shape.

**Bounds: six games are broken at the size they themselves claim to support.**

| Game | Line | Problem at declared min size |
|---|---|---|
| Connect Four | 3564-3567 | `min_h = 18` but the hint is written at y=18. **The controls line is silently invisible.** |
| Pac-Man | 2683, 2718 | 35-char header and 43-char hint into `min_w = 30`. Lives counter cut off. |
| Sokoban | 2891 | 44-char hint into `min_w = 30`. |
| Reversi | 3161 | 40-char hint drawn at x=7 in a 34-col terminal. |
| Minesweeper | 2336 | 49-char hint into `min_w = 40`. Loses `ESC:Quit`. |
| Snake | 659 | 38-char hint at x=2 with `min_w = 30`. Loses `ESC:Quit`. |

Also: `safe_addstr` **drops the whole string on negative x** (293) instead of clipping the left side, which is why Dino obstacles pop out of existence (`dino-8`). Flappy does it right, clipping per column (2140). Shooter never clamps `player_x` in `update()`, only in `handle_input` (1462-1464), so a shrink hides the ship until the player presses a key.

**Resize: `curses.KEY_RESIZE` (410) is never referenced and `curses.resize_term` is never called.** Consequences: the key is forwarded to `handle_input` (483) and **counts as a game turn in every turn-based game** (498); on windows-curses `getmaxyx()` keeps returning the stale size; boards are sized once in `setup()` from the startup terminal and never resized (Snake 571, Breakout 1234), so maximizing leaves a 52-col Breakout board floating in a 200-col window; Flappy dies instantly on shrink (`flappy-5`); Pong gifts points on shrink (`pong-8`). The too-small gate itself (471-479) is good: it runs *before* `update()` and resyncs `next_tick` so no time is banked.

**Unicode: there is no ASCII fallback anywhere.** No encoding probe, no `_ASCII` flag. `draw_box` (308-312) uses `┌─┐│└┘` (Snake 650, Tetris 808, Breakout 1360, help overlay 345); 2048 (1000-1019) and Connect Four (3544-3557) use the full `┌┬┐├┼┤└┴┘│` set; the menu title (3619-3621) uses double-line `╔═╗║╚╝`. **Dino is the worst offender:** `_DINO` and `_CACTUS_*` (1040-1046) use quadrant block elements `▟◣◢▛▙▖▗▝▘` (U+2596..U+259F). cp437/cp850 have `█▄▀` but **none of the quadrant glyphs**, so on a legacy Windows console the dino and cacti become `?` or mojibake and the sprite is unreadable. The only mitigation, `_stream.reconfigure(encoding='utf-8')` at 4631-4635, is **useless for curses** (curses writes through its own C-level output, not `sys.stdout`); it only protects the `play cli` text renderers. Under `LANG=C` the box chars turn to garbage with no fallback.

**Teardown: safe.** `_curses_wrapper` delegates to `curses.wrapper` (138), whose `finally` restores `endwin`/`nocbreak`/`echo` including on `KeyboardInterrupt`. `_net_menu` closes the socket in a `finally` (3970-3974). But `main()` has no top-level `try` (4628-4700), so Ctrl-C during any game dumps a full traceback into the restored terminal, and `curses.wrapper` does not restore cursor visibility (`curs_set(0)` at 421, 3648, 3671, 3965 with no matching `curs_set(1)` in a finally).

**Visual identity: nine of fourteen games have no frame whatsoever.** Only 5 have a border (Snake 650, Tetris 808, Breakout 1360, 2048 1000-1019, Connect Four 3544-3557).

- Genuinely distinct: **Tetris** (well + side panel + ghost piece), **2048** (full cell grid, per-value color), **Connect Four** (boxed grid, column picker `v`), **Breakout** (title inlaid in the border), **Dino** (block-art sprite, ground rule, speed dots), **Frogger** (lane textures `~ # [o] ^ -`).
- Offenders: **Minesweeper** (2314-2334, a bare field of `#`, no border, no separators), **Pac-Man** (2687-2711, plain ASCII maze with no border, and **all four ghosts plus the frightened state all render as `M`**, so on a mono terminal Blinky, Pinky, Inky, Clyde and "edible" are indistinguishable), **Sokoban** (2874-2890, a 5x3 ASCII box adrift in an empty 30x16 screen on level 1), **Reversi** (3144-3158, an 8x8 field of `.` with no grid lines, sitting right next to a fully box-drawn Connect Four), **Space Shooter** (1667-1740, a completely unframed void, no border, no starfield, no HUD panel).
- All 14 have a hint line, but none is a real status bar (no reverse-video full-width row), placement is inconsistent (Tetris has no bottom line at all, putting controls in the side panel at 853-858), and six are truncated or invisible at their own min size. There is no shared status-bar helper on `Game`.

---

## 7. Prioritized bug and pacing list

Worst first. This is the spec the fix phase executes against.

| # | ID | Game | Category | Sev | Description | Lines |
|---|---|---|---|---|---|---|
| 1 | `frogger-1` | Frogger | bug | **HIGH** | Unlimited hops per tick: the frog teleports through road and river rows with zero collision checks. Hold Up = instant win. Invalidates the whole game. | 3246-3257, 3282-3318 |
| 2 | `dino-1` | Dino | bug | **HIGH** | The XL cactus is mathematically unjumpable at starting speed (2 safe ticks vs a 3-tick danger window). Guaranteed death, 12% of early spawns, for the first ~17 s of every run. | 1078-1079, 1104, 1136-1149, 1155 |
| 3 | `shooter-1` | Shooter | canon | **HIGH** | Unlimited autofire: no bullet cap, no cooldown. Up to 150 bullets/sec against a 20 Hz sim. | 1465-1473 |
| 4 | `flappy-3` | Flappy | input | **HIGH** | Holding W/Space is a guaranteed self-kill: auto-repeat re-assigns flap velocity faster than gravity, and the climb ends at a lethal ceiling. | 2087-2089, 2099 |
| 5 | `reversi-4` / `2048-2` | Reversi, 2048 | input | **HIGH** | The keypress that dismisses the help overlay is consumed as a game move. In Reversi it commits an irreversible disc; in 2048 it slides and spawns. One-line base-loop fix protects every game. | 461-466, 483-484 |
| 6 | `pacman-1` | Pac-Man | canon | **HIGH** | No scatter/chase timer exists at all. The ghosts chase relentlessly from frame 1 and the game never breathes. | 2493-2580, 2597-2660 |
| 7 | `pacman-3` | Pac-Man | canon | **HIGH** | Inky is a pure random walker with no target. The most interesting ghost is an RNG. | 2396, 2533-2548 |
| 8 | `c4-1` | Connect Four | pacing | **HIGH** | No drop animation and no AI think delay: human disc and AI disc appear in the same single redraw. `'AI is thinking...'` (3577) is unreachable dead code. | 3479-3527 |
| 9 | INFRA-1 | Breakout, Pong, Shooter, Frogger, Tetris | input | **HIGH** | Player motion lives in `handle_input()`, so paddle/ship/frog speed is the OS key auto-repeat rate, with the forbidden ~0.5 s start delay. Commit 73a872c fixed the world clock, not the player clock. Coalesce input per tick. | 1285, 1842, 1459, 3246, 777 |
| 10 | NET-1 | Reversi, C4 | multiplayer | **HIGH** | One lost move frame = permanent silent deadlock. No ack, no sequence number, no resend. `send()` can write a partial line and drop the rest. | 3391-3399, 3114-3115 |
| 11 | NET-2 | all net | multiplayer | **HIGH** | `?` and a terminal resize freeze the network game for both players, because `update()` is the only thing that touches the socket and it is gated on `active`. | 466, 471-479, 490, 499 |
| 12 | `shooter-2` | Shooter | canon | med | Regular enemies never fire a single shot; only the boss shoots. Waves 1-4, 6-9, 11-14 have zero incoming projectiles. | 1540-1550 |
| 13 | `breakout-1` | Breakout | pacing | med | The 4-tier ball-speed ratchet is entirely missing. `ball_dy` magnitude is permanently 1.0. Zero difficulty curve across the whole game. | 1245-1246, 1313-1343 |
| 14 | `breakout-3` | Breakout | canon | med | Paddle never halves on top-wall contact. The game's signature risk/reward beat is absent. | 1239, 1312-1314 |
| 15 | `tetris-1` | Tetris | canon | med | No lock delay at all. The grace window is a random 0 to `drop_interval`. | 795-802, 777-780 |
| 16 | `tetris-2` | Tetris | canon | med | Rotation has horizontal-only kicks and no floor kick. A T or I on the surface can never rotate. T-Spin Triple is impossible. | 684-685, 781-787 |
| 17 | `tetris-4` | Tetris | input | med | Hard drop auto-repeats: holding Space chain-drops every new piece and tops you out in seconds. | 788-793 |
| 18 | `tetris-5` | Tetris | bug | med | Pause or `?` with a piece resting on the stack locks it instantly on resume (`last_drop` is raw wall clock). | 706, 713, 796-802 |
| 19 | `tetris-3` | Tetris | canon | med | Uniform `random.choice` instead of the 7-bag: unbounded I-droughts and S/Z floods. | 711, 728 |
| 20 | `pong-8` | Pong | render | med | Solo mode derives the playfield from the live terminal size every tick. Shrinking the window gifts free points and strands the paddles. | 1758-1762, 1946-1957 |
| 21 | `flappy-5` | Flappy | bug | med | A terminal resize relocates the ground and kills the bird instantly. `setup()` guards this; `update()` does not. | 2098-2100 |
| 22 | `flappy-4` | Flappy | pacing | med | No fall clamp: a dive reaches 3.5 rows/tick, half a pipe gap per drawn frame at 20 FPS. | 2095-2096 |
| 23 | `flappy-2` | Flappy | canon | med | The ceiling is lethal. Canon: solid but harmless. Exactly two lethal surfaces, not three. | 2098-2101 |
| 24 | `2048-1` | 2048 | bug | med | A loss after reaching 2048 is announced as "YOU WIN!". The sticky `won` flag is never cleared, and is persisted across sessions. | 944-947, 515-520 |
| 25 | `pacman-6` | Pac-Man | pacing | med | Frightened ghosts do not slow down, fright is 2.4 s vs canon 6 s, and late-game ghosts move at exactly Pac-Man's speed. Eating a ghost is luck. | 2499-2515, 2653-2655 |
| 26 | `pacman-9` | Pac-Man | bug | med | Frightened ghosts and random-Inky ignore the ghost door and can hide in the pen, where Pac-Man cannot follow. Un-eatable. | 2499-2515, 2533-2548 |
| 27 | `pacman-10` | Pac-Man | canon | med | Winning ends the game. No level progression, so the entire difficulty ramp is missing. | 2638-2641 |
| 28 | `pacman-4` | Pac-Man | canon | med | Ghost-eating is a flat 200. No 200/400/800/1600 chain. | 2662-2674 |
| 29 | `pacman-11` | Pac-Man | canon | med | Ghost AI uses the global RNG unseeded. The game cannot be patterned. | 2502, 2535 |
| 30 | `shooter-7` | Shooter | canon | med | No formation, so no alive-count acceleration. `spawn_rate`/`enemy_speed` are never modified after setup: late waves are longer, not harder. | 1475-1485, 1652-1665 |
| 31 | `snake-1` | Snake | input | med | Single-slot direction buffer with enqueue-time validation silently swallows the second turn of a fast L-turn. | 609-621 |
| 32 | `snake-2` | Snake | canon | med | No board-full win state; the food spawner leaves a phantom pellet under the snake. `self.won` is never assigned. | 597-602 |
| 33 | `frogger-2` | Frogger | canon | med | No timer at all. The 30-second clock, death by timeout, and the time bonus are absent. `self.frame` is written but never read. | 3214-3237 |
| 34 | `frogger-3` | Frogger | canon | med | No level progression, no difficulty scaling. `supports_difficulty` left False, so the picker is skipped. | 3266-3280, 279 |
| 35 | `breakout-2` | Breakout | input | med | Paddle moves 3 cells per key EVENT. (Instance of INFRA-1; listed separately for the fix.) | 1285-1294 |
| 36 | `reversi-1` | Reversi | canon | med | The player's own pass message is overwritten before it is ever drawn. The board changes twice in one turn with no explanation. | 3097-3121 |
| 37 | `reversi-3` | Reversi | pacing | med | Zero flip animation and zero AI think pause. A 12-disc swing is an instant state teleport. | 3056-3121 |
| 38 | `reversi-7` | Reversi | multiplayer | med | A peer that disconnects while it is YOUR turn is never detected, because `poll()` is only reached on the opponent's branch. | 3079, 3097-3112 |
| 39 | `reversi-11` | Reversi | bug | med | Negamax evaluates the horizon before the terminal check and burns a ply on every pass. The "endgame solve" never solves the endgame. | 3013-3025, 3041 |
| 40 | `c4-2` | Connect Four | render | med | The game-over banner is stamped through the middle of the board and destroys the winning line. | 3529-3558, 513-537 |
| 41 | `c4-7` | Connect Four | multiplayer | med | The LAN guest plays as O but is told "Your turn (X)" for the entire game. | 3572-3577 |
| 42 | `dino-3` | Dino | render | med | Ground parallax dots scroll RIGHT while obstacles scroll LEFT. Reads as the dino running backwards. | 1186-1188 |
| 43 | INFRA-2 | all | bug | med | `KEY_RESIZE` is never referenced. It is forwarded to `handle_input` and **counts as a free game turn** in every turn-based game. `curses.resize_term` is never called. | 410, 483, 498 |
| 44 | INFRA-3 | Snake, Breakout, Minesweeper, Flappy, Pong, Shooter | bug | med | `_fit_bounds` is never re-run on resize; boards are sized once from the startup terminal. Collision bounds desync from the drawn board. | 585, 1264, 2211 |
| 45 | INFRA-4 | all | render | med | `_game_over_screen` never erases and never redraws, so the last live frame bleeds through and a resize while it is up leaves the screen permanently garbled. | 513-547 |
| 46 | NET-3 | all net | multiplayer | med | No heartbeat and no timeout. A pulled cable hangs forever; only ESC escapes. | 3381-3428 |
| 47 | NET-4 | all net | multiplayer | med | LAN results are written into the single-player high-score table with no `if self.net` guard. Beating a friend counts as beating the AI. | 522-524 |
| 48 | NET-5 | Pong | multiplayer | med | No `TCP_NODELAY`. Nagle plus delayed-ACK on a 110-byte-every-40 ms stream. One-line fix, biggest single win for Pong feel. | 3384-3389 |
| 49 | NET-6 | Pong | multiplayer | med | The guest can never serve. After the guest scores, the match is frozen until the HOST presses SPACE. No serve timer. | 1844-1854 |
| 50 | INFRA-5 | all | bug | med | All JSON writes are non-atomic and racy across the multiple processes `_open_in_terminal` encourages. | 187, 232, 395, 4517 |
| 51 | `snake-3` | Snake | pacing | low | The catch-up loop can advance the snake 3 cells between rendered frames with one key read: 3 unsteerable, unseen moves. | 486-497 |
| 52 | `breakout-6` | Breakout | bug | low | The ball speed cap (1324-1328) is unreachable dead code on every possible input. | 1324-1328 |
| 53 | `shooter-5` | Shooter | pacing | low | Player bullet and enemy bullet are the same speed. Canon demands 3:1. | 1514-1517 |
| 54 | `shooter-12` | Shooter | bug | low | A restored save is `setattr`'d with no clamping, so the ship can start off-screen and difficulty comes from the save, not the picker. | 1403-1408 |
| 55 | `shooter-13` | Shooter | render | low | At `min_w = 40` the powerup status and the control footer overlap on the same row. | 1735-1740 |
| 56 | `pong-5` | Pong | canon | low | Serve direction is inverted: the ball is served AWAY from the player who just missed. | 1946-1957, 1833-1840 |
| 57 | `tetris-7` | Tetris | render | low | O and L both map to color pair 3 (YELLOW). Retro and Ocean themes collide more pieces. | 681, 196-207 |
| 58 | `tetris-11` | Tetris | canon | low | No buffer zone: pieces spawn inside the visible matrix, so there is no Lock Out and the top two rows are unusable. | 690, 726-733 |
| 59 | `2048-5` | 2048 | render | low | The game-over text is painted over the grid with no erase, shredding the final board. | 501-503, 513-537 |
| 60 | `dino-8` | Dino | render | low | Obstacles vanish instantly at the left edge because `safe_addstr` bails on `x < 0` instead of clipping. | 291-295, 1179-1183 |
| 61 | `flappy-6` | Flappy | canon | low | Gap placement has no margin band: gaps can hug the ceiling (1-row pipe) or the floor. | 2105-2107 |
| 62 | `flappy-9` | Flappy | canon | low | No Get Ready state: the bird falls on tick 1 before the player presses anything. | 2076-2082 |
| 63 | `flappy-10` | Flappy | canon | low | No death sequence: collision jumps straight to the game-over screen, no freeze, no nose-down fall. | 2099-2101 |
| 64 | `flappy-11` | Flappy | canon | low | No medals. The stats line advertises the non-canonical speed multiplier instead. | 2163-2164 |
| 65 | `mines-1` | Minesweeper | canon | low | Chording is completely missing. The entire speed game of Minesweeper is absent. | 2277-2291, 2256-2258 |
| 66 | `mines-2` | Minesweeper | pacing | low | The timer starts at new-game, not at the first reveal, and is a lossy tick counter that pause and a resize can stop. | 2293-2295, 2306 |
| 67 | `mines-4` | Minesweeper | canon | low | No detonated-mine highlight, no X on wrong flags, no auto-flag on win. | 2262-2265, 2318-2333 |
| 68 | `mines-5` | Minesweeper | bug | low | Cross-difficulty high score is a saturating cell count. One hard win writes 381 and easy/medium can never register again. | 2249, 2199-2200 |
| 69 | `pacman-16` | Pac-Man | canon | low | No bonus fruit and no extra life at 10,000. The score curve is flat. | 2622-2636, 2662-2674 |
| 70 | `sokoban-3` | Sokoban | render | low | The solved board is never rendered: `update()` advances the level before `draw()` runs. The completion frame, the entire payoff, is never shown. | 483-503, 2855-2865 |
| 71 | `reversi-2` | Reversi | canon | low | The AI's pass sets no message at all. The human is handed two turns in a row with no explanation. | 3104-3107 |
| 72 | `reversi-6` | Reversi | multiplayer | low | Network disconnect always reports the BLACK disc count as your score, even when you are white. | 3079-3083 |
| 73 | `reversi-9` | Reversi | canon | low | A 32-32 draw is shown as a red "GAME OVER". Perfect play is a draw. | 3051-3054 |
| 74 | `c4-4` | Connect Four | input | low | Number keys 1-7 are not accepted, though the board prints 1-7 labels and the CLI variant accepts them. | 3496-3507 |
| 75 | `c4-5` | Connect Four | input | low | Dropping into a full column is a silent no-op, and the hover ghost still shows over full columns. | 3503-3507, 3537-3542 |
| 76 | `c4-6` | Connect Four | render | low | The last placed disc is not distinguished and the winning four is not highlighted. The CLI variant tracks this; the curses game is the regression. | 3548-3554 |
| 77 | `c4-8` | Connect Four | multiplayer | low | Opponent disconnect goes undetected while it is your turn. | 3509-3523 |
| 78 | `frogger-4` | Frogger | bug | low | River spawner wrap off-by-one fuses two logs into a permanent 9-cell mega-platform in all three river rows. | 3220-3228 |
| 79 | `frogger-5` | Frogger | canon | low | The river is one homogeneous log type. No turtles, no diving, no fly, no lady frog, no gators. | 3187-3197 |
| 80 | `frogger-10` | Frogger | render | low | On the final life, an edge death leaves the frog drawn one column outside the field. | 3310-3312 |
| 81 | INFRA-6 | Flappy, Pac-Man | perf | low | `load_high_score()` is called inside `draw()`, so these two games do ~50 JSON file reads per second for the entire session. | 2128, 2682 |
| 82 | INFRA-7 | 6 games | render | low | Control hints are truncated or invisible at each game's own declared min size (C4, Pac-Man, Sokoban, Reversi, Minesweeper, Snake). | see 6 |
| 83 | INFRA-8 | all | render | low | No ASCII fallback for box-drawing or block glyphs. Dino's quadrant blocks (U+2596-259F) are absent from cp437/cp850 and become mojibake on a legacy Windows console. | 1040-1046, 308-312 |
| 84 | INFRA-9 | Tetris | bug | low | Tetris keeps a second, non-monotonic (`time.time()`) clock parallel to the base tick. | 795-803 |
| 85 | INFRA-10 | all | bug | low | `run()`'s bare `except Exception` around `setup()` hides genuine game bugs behind a silent restart. | 424-433 |
| 86 | INFRA-11 | launcher | bug | low | `_open_in_terminal` returns True and prints "Opened in a new terminal window" even when the X terminal died instantly (no `$DISPLAY`), and builds an injectable shell string for the xterm/konsole branch. | 112-121 |
| 87 | NET-7 | all net | multiplayer | low | `SO_REUSEADDR` on Windows lets two hosts bind the same actively-listening port. Windows wants `SO_EXCLUSIVEADDRUSE`. This repo's user is on Windows. | 3884 |
| 88 | NET-8 | all net | multiplayer | low | Rematch is broken: `_game_over_screen` returns `'retry'` but `_net_menu` ignores the return value, so R silently quits to the menu. | 3971 |
| 89 | INFRA-12 | tests | test | low | There is **no network test at all**, despite the README claiming one (line 164-165). `main()`, argv parsing and `_curses_wrapper` are also untested. | tests/test_games.py |
| 90 | INFRA-13 | CLI | bug | low | `GAME_STATE_FILE` is a single global slot shared by all four CLI games. `play cli start 2048` silently destroys an in-progress CLI snake. | 156, 4515 |
