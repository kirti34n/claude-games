try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class SokobanGame(Game):
    name = "sokoban"
    min_h = 16
    # The header (title, level, moves, pushes) does not scale with the
    # tiny board (5-7 columns): a fixed floor of 30 was narrower than the
    # header's own 39-44 chars, silently dropping the Pushes counter --
    # the one stat Sokoban is actually scored on. 40 comfortably fits the
    # compacted header (see draw()) at any level/move count this game can
    # realistically reach.
    min_w = 40
    # '#' wall, '.' target, '$' box, '*' box-on-target, '@' player, '+' player-on-target
    #
    # 20 ORIGINAL levels, increasing difficulty, replacing the old 4-level
    # placeholder set (whose "whole game" optimum was 15 moves total -- L1
    # was a single push right, L2 a single push down). Every level below
    # was verified solvable under the EXACT push-only mechanics this file
    # implements (a box can be pushed, never pulled). Levels are not copied
    # from any existing Sokoban set (no network access was available to
    # fetch one); they're original, generated and solvability-checked by a
    # script, not merely eyeballed.
    #
    # Every level's move/push counts below are PROVEN OPTIMAL (shortest
    # possible) by an exhaustive breadth-first search over the full
    # game-state graph (player pos x box set) -- levels 10-20 included:
    # keeping their floor plans to narrow, mostly 1-wide corridors (see
    # below) kept the state space small enough for the search to finish
    # even at 8-9 boxes.
    #
    # Levels 10-20 (correctness re-audit finding: the old set 10-20 was a
    # single "comb" puzzle -- one box per 1-wide corridor with its target
    # directly above it -- re-emitted at 11 different sizes; a
    # zero-intelligence "walk under each box, push it straight up, repeat"
    # plan solved all 11 with no search, no ordering, and no way to make a
    # wrong move) are REBUILT as genuinely distinct, multi-box, 2D layouts
    # (a shared room in 10-12, then a family of cross/H/staircase floor
    # plans in 13-20, each a DIFFERENT shape, not the same shape resized):
    # boxes must be approached from different sides in different directions
    # (up/down/left/right, not always "push up"), and several levels
    # require navigating the player around multiple already-placed boxes to
    # reach the next one. They were designed by CONSTRUCTING backwards from
    # the solved position (every box starting on its target) via legal
    # reverse-pushes ("pulls"), which guarantees solvability by
    # construction, and were then independently re-verified by the same
    # exhaustive BFS as levels 1-9 (not just the constructed witness path),
    # so the table below is the true shortest solution, not merely a
    # working one.
    #
    # Lvl  Boxes  Moves  Pushes  Proof
    #   1    1       4       1   optimal (BFS)
    #   2    1       3       2   optimal (BFS)
    #   3    4       7       4   optimal (BFS)
    #   4    1      10       5   optimal (BFS)
    #   5    2      17       3   optimal (BFS)
    #   6    3      23       5   optimal (BFS)
    #   7    2      26       6   optimal (BFS)
    #   8    3      30      16   optimal (BFS)
    #   9    2      31      13   optimal (BFS)
    #  10    4      16       4   optimal (BFS)
    #  11    5      25      10   optimal (BFS)
    #  12    6      25       6   optimal (BFS)
    #  13    6      27      16   optimal (BFS)
    #  14    7      45      22   optimal (BFS)
    #  15    7      42      19   optimal (BFS)
    #  16    8      56      28   optimal (BFS)
    #  17    8      48       9   optimal (BFS)
    #  18    8      62      28   optimal (BFS)
    #  19    9      73      34   optimal (BFS)
    #  20    9      80      38   optimal (BFS)
    _LEVELS = [
        ["########",
         "#  #   #",
         "#  #.  #",
         "#  #$  #",
         "#@     #",
         "#  #   #",
         "########"],
        ["########",
         "#  #   #",
         "#  #   #",
         "#@ $ . #",
         "#  #   #",
         "#  #   #",
         "########"],
        ["#######",
         "#  .  #",
         "# #$# #",
         "#.$@$.#",
         "# #$# #",
         "#  .  #",
         "#######"],
        ["#########",
         "#.  #   #",
         "#   #   #",
         "# ###   #",
         "#  $    #",
         "#     @ #",
         "#########"],
        ["##########",
         "#    #   #",
         "# .  # . #",
         "#  $   $ #",
         "#  #  #  #",
         "#  @     #",
         "##########"],
        ["############",
         "#    #     #",
         "# .  #  .  #",
         "#    #     #",
         "# $     $  #",
         "#    #     #",
         "#    #  .  #",
         "#  @    $  #",
         "#          #",
         "############"],
        ["###########",
         "#.    #   #",
         "# ##  #   #",
         "#  #$ #.  #",
         "#  #  #$  #",
         "#  #  #   #",
         "#  @  ## ##",
         "#  #      #",
         "###########"],
        ["###########",
         "#.  .  .  #",
         "#         #",
         "#  #   #  #",
         "#  $ $ $  #",
         "#  #   #  #",
         "#    @    #",
         "###########"],
        ["#########",
         "#   #   #",
         "# @ # . #",
         "#  $$   #",
         "# . #   #",
         "#   #   #",
         "#########"],
        ["#############",
         "#  .     .  #",
         "#  $     $  #",
         "#     @     #",
         "#  $     $  #",
         "#  .     .  #",
         "#############"],
        ["###############",
         "#  .       .  #",
         "#  $       $  #",
         "#  $   . @    #",
         "#  $       $  #",
         "#  .       .  #",
         "###############"],
        ["###############",
         "###.#######.###",
         "###$#######$###",
         "###  . #    ###",
         "#   @$   $    #",
         "###    # .  ###",
         "###$#######$###",
         "###.#######.###",
         "###############"],
        ["#############",
         "###### ######",
         "######.######",
         "###### $ .###",
         "###### ######",
         "######$######",
         "# .  $@$  . #",
         "######$######",
         "###### ######",
         "###. $ ######",
         "######.######",
         "###### ######",
         "#############"],
        ["###############",
         "#######.#######",
         "####### #######",
         "####### $ .####",
         "####### #######",
         "#######$#######",
         "####### #######",
         "#.   $  @$   .#",
         "###$### #######",
         "### ###$#######",
         "###.### #######",
         "####. $ #######",
         "####### #######",
         "#######.#######",
         "###############"],
        ["###############",
         "### ####### ###",
         "###.#######.###",
         "### ####### ###",
         "### ####### ###",
         "### ###.### ###",
         "###$###$###$###",
         "###        @###",
         "###$#$###$#$###",
         "### #.###.# ###",
         "### ####### ###",
         "### ####### ###",
         "###.#######.###",
         "### ####### ###",
         "###############"],
        ["#################",
         "########.########",
         "######## ########",
         "######## $ .#####",
         "######## ########",
         "######## ####.###",
         "########$#### ###",
         "######## ####$###",
         "#.    $  @$    .#",
         "###$#### ########",
         "### ####$########",
         "###.#### ########",
         "######## ########",
         "#####. $ ########",
         "######## ########",
         "########.########",
         "#################"],
        ["#################",
         "#################",
         "##.$   $.########",
         "####$# ##########",
         "#### # ##########",
         "####.# ##########",
         "######       ####",
         "######### #$#####",
         "######### #.#####",
         "######### #######",
         "###.$     #######",
         "#####$## ########",
         "#####.## ###.####",
         "######## ###$####",
         "########    @$.##",
         "#################",
         "#################"],
        ["###################",
         "#########.#########",
         "######### #########",
         "######### $ .######",
         "######### #########",
         "######### #########",
         "#########$#####.###",
         "######### ##### ###",
         "######### #####$###",
         "#.    $    @$    .#",
         "###$##### #########",
         "### ##### #########",
         "###.#####$#########",
         "######### #########",
         "######### #########",
         "######. $ #########",
         "######### #########",
         "#########.#########",
         "###################"],
        ["#####################",
         "##########.##########",
         "########## ##########",
         "########## $ .#######",
         "########## ##########",
         "########## ##########",
         "########## ##########",
         "#######. $$######.###",
         "########## ###### ###",
         "########## ######$###",
         "#.     $    @$     .#",
         "###$###### ##########",
         "### ###### ##########",
         "###.######$##########",
         "########## ##########",
         "########## ##########",
         "########## ##########",
         "#######. $ ##########",
         "########## ##########",
         "##########.##########",
         "#####################"],
        ["#######################",
         "###########.###########",
         "########### ###########",
         "########### $ .########",
         "########### ###########",
         "########### ###########",
         "########### ###########",
         "########. $ ###########",
         "###########$#######.###",
         "########### ####### ###",
         "########### #######$###",
         "#.      $    @$      .#",
         "###$####### ###########",
         "### ####### ###########",
         "###.#######$###########",
         "########### ###########",
         "########### ###########",
         "########### ###########",
         "########### ###########",
         "########. $ ###########",
         "########### ###########",
         "###########.###########",
         "#######################"],
    ]

    def setup(self):
        saved = self._load_save(self.name)
        if saved:
            self.level_idx = saved['level']
            self._parse_level(self.level_idx)
            self.boxes = {tuple(b) for b in saved['boxes']}
            self.py, self.px = saved['py'], saved['px']
            self.moves = saved['moves']
            self.pushes = saved['pushes']
            self.score = saved['score']
            self._total_moves = saved.get('total_moves', 0)
            self._total_pushes = saved.get('total_pushes', 0)
            self.history = []
            return
        self.level_idx = 0
        self.score = 0
        self._total_moves = 0
        self._total_pushes = 0
        self._start_level(self.level_idx)

    def _parse_level(self, idx):
        rows = self._LEVELS[idx]
        self.rows = len(rows)
        self.cols = max(len(r) for r in rows)
        self.walls = set()
        self.targets = set()
        self._init_boxes = set()
        self._init_player = (1, 1)
        for r, line in enumerate(rows):
            for c, ch in enumerate(line):
                if ch == '#':
                    self.walls.add((r, c))
                elif ch in '.+*':
                    self.targets.add((r, c))
                if ch in '$*':
                    self._init_boxes.add((r, c))
                if ch in '@+':
                    self._init_player = (r, c)
        # NOTE: this used to overwrite self.min_w/self.min_h with
        # max(40, cols+4) / max(16, rows+6) here, growing them per-level up
        # to 29 rows for level 20. That made the class-declared min_h=16 a
        # lie (the run loop's too-small gate reads the INSTANCE attribute,
        # which had already grown past it) and left levels 18-20 physically
        # unreachable on a stock 80x24 terminal -- the 20-level campaign
        # could never be finished there. draw() now scrolls a viewport
        # clamped to the class-declared min_h/min_w instead of demanding
        # the whole board fit on screen at once, so the declared minimum
        # stays true for every level and nothing is ever unreachable.

    def _start_level(self, idx):
        self._parse_level(idx)
        self.boxes = set(self._init_boxes)
        self.py, self.px = self._init_player
        self.history = []
        # Moves/Pushes in the header are PER-LEVEL (that's how the header
        # reads: "Level X/Y  Moves:N  Pushes:N"), so every fresh level
        # attempt -- including natural advancement, not just a manual R --
        # starts them at 0. Before this, only R reset them, so completing
        # level 1 and starting level 2 kept level 1's counts silently
        # baked into level 2's displayed total. The game-long totals still
        # accumulate separately (see _total_moves/_total_pushes) for the
        # end-of-game stats screen.
        self.moves = 0
        self.pushes = 0

    def get_timeout(self):
        return -1  # turn-based: block until a key is pressed

    def _in_bounds(self, y, x):
        return 0 <= y < self.rows and 0 <= x < self.cols

    def _move(self, dy, dx):
        ny, nx = self.py + dy, self.px + dx
        if not self._in_bounds(ny, nx) or (ny, nx) in self.walls:
            return
        if (ny, nx) in self.boxes:
            by, bx = ny + dy, nx + dx
            if (not self._in_bounds(by, bx) or (by, bx) in self.walls
                    or (by, bx) in self.boxes):
                return
            self.history.append((self.py, self.px, set(self.boxes), True))
            self.boxes.discard((ny, nx))
            self.boxes.add((by, bx))
            self.py, self.px = ny, nx
            self.moves += 1
            self.pushes += 1
        else:
            self.history.append((self.py, self.px, set(self.boxes), False))
            self.py, self.px = ny, nx
            self.moves += 1

    def handle_input(self, key):
        if key in (curses.KEY_UP, ord('w')):
            self._move(-1, 0)
        elif key in (curses.KEY_DOWN, ord('s')):
            self._move(1, 0)
        elif key in (curses.KEY_LEFT, ord('a')):
            self._move(0, -1)
        elif key in (curses.KEY_RIGHT, ord('d')):
            self._move(0, 1)
        elif key in (ord('u'), ord('z')):
            if self.history:
                self.py, self.px, self.boxes, was_push = self.history.pop()
                self.moves = max(0, self.moves - 1)
                if was_push:
                    self.pushes = max(0, self.pushes - 1)
        elif key in (ord('r'), ord('R')):
            self._start_level(self.level_idx)  # also zeroes moves/pushes

    def update(self):
        if self.game_over:
            return
        if self.boxes == self.targets:
            self.score += 1  # one point per solved level
            # Hold the solved frame (every box drawn as '*' on target) on
            # screen before the board changes underneath it. Without this,
            # the level swap (or the game-over transition) happens inside
            # this same update() and the payoff frame is never drawn.
            for _ in self.animate((250, 250, 250)):
                self.stdscr.erase()
                self.draw()
            self._total_moves += self.moves
            self._total_pushes += self.pushes
            if self.level_idx + 1 < len(self._LEVELS):
                self.level_idx += 1
                self._start_level(self.level_idx)
            else:
                self.won = True
                self.game_over = True

    def _viewport(self):
        # Camera window clamped to the board's own edges, so it never
        # scrolls past them and wastes blank space, and centered on the
        # player otherwise. When the whole board fits on screen this
        # degenerates to (0, 0, rows, cols) -- the old unscrolled behavior.
        avail_h = max(1, self.h - 3)  # header row above, status bar below
        avail_w = max(1, self.w - 2)  # a column of margin each side
        view_h = min(self.rows, avail_h)
        view_w = min(self.cols, avail_w)
        top = max(0, min(self.py - view_h // 2, self.rows - view_h))
        left = max(0, min(self.px - view_w // 2, self.cols - view_w))
        return top, left, view_h, view_w

    def draw(self):
        top, left, view_h, view_w = self._viewport()
        scrolled = view_h < self.rows or view_w < self.cols
        if view_h < self.rows:
            off_y = 1
        else:
            off_y = max(1, (self.h - self.rows - 3) // 2)
        if view_w < self.cols:
            off_x = max(0, (self.w - view_w) // 2)
        else:
            off_x = max(0, (self.w - self.cols) // 2)
        # Compact, single-spaced form: the old double-spaced header (39-44
        # chars) exceeded its own declared min_w=30, silently dropping the
        # Pushes counter -- the stat Sokoban is actually scored on.
        header = (f' SOKOBAN Lv{self.level_idx + 1}/{len(self._LEVELS)}'
                  f' Moves:{self.moves} Pushes:{self.pushes}'
                  f'{" [scrolling]" if scrolled else ""} ')
        self.safe_addstr(off_y - 1, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD)
        for r in range(view_h):
            for c in range(view_w):
                cell = (top + r, left + c)
                if cell in self.walls:
                    ch, attr = '#', curses.color_pair(6) | curses.A_BOLD
                elif cell == (self.py, self.px):
                    ch = '+' if cell in self.targets else '@'
                    attr = curses.color_pair(4) | curses.A_BOLD
                elif cell in self.boxes:
                    on = cell in self.targets
                    ch = '*' if on else '$'
                    attr = curses.color_pair(1 if on else 2) | curses.A_BOLD
                elif cell in self.targets:
                    ch, attr = '.', curses.color_pair(3) | curses.A_BOLD
                else:
                    ch, attr = ' ', 0
                self.safe_addstr(off_y + r, off_x + c, ch, attr)
        # List form so the escape hatches (Esc:Quit, ?:Help) always survive
        # at min width even though '?:Help' was never advertised before
        # (INFRA-7), despite get_controls() below defining a help overlay
        # the player had no way to discover.
        self.draw_status_bar(['WASD:Move', 'U:Undo', 'Esc:Quit', '?:Help'])

    def get_controls(self):
        return [('WASD/Arrows', 'Push boxes'), ('U / Z', 'Undo move'),
                ('R', 'Reset level'), ('ESC', 'Quit / save')]

    def get_stats(self):
        return [('Levels solved', self.score),
                ('Total moves', self._total_moves + self.moves),
                ('Total pushes', self._total_pushes + self.pushes)]

    def get_save_data(self):
        return {'level': self.level_idx, 'boxes': [list(b) for b in self.boxes],
                'py': self.py, 'px': self.px, 'moves': self.moves,
                'pushes': self.pushes, 'score': self.score,
                'total_moves': self._total_moves,
                'total_pushes': self._total_pushes}
