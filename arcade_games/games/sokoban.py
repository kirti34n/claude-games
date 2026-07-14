try:
    import curses
except ImportError:
    curses = None

from ..game import Game


class SokobanGame(Game):
    name = "sokoban"
    min_h = 16
    min_w = 30
    # '#' wall, '.' target, '$' box, '*' box-on-target, '@' player, '+' player-on-target
    _LEVELS = [
        ["#####",
         "#@$.#",
         "#####"],
        ["#####",
         "#@  #",
         "#$  #",
         "#.  #",
         "#####"],
        ["######",
         "#@ $.#",
         "# $ .#",
         "######"],
        ["#######",
         "#  .  #",
         "# #$# #",
         "#.$@$.#",
         "# #$# #",
         "#  .  #",
         "#######"],
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
            self.history = []
            return
        self.level_idx = 0
        self.moves = 0
        self.pushes = 0
        self.score = 0
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
        self.min_w = max(30, self.cols + 4)
        self.min_h = max(16, self.rows + 6)

    def _start_level(self, idx):
        self._parse_level(idx)
        self.boxes = set(self._init_boxes)
        self.py, self.px = self._init_player
        self.history = []

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
            self._start_level(self.level_idx)
            self.moves = 0  # a manual reset abandons this attempt entirely
            self.pushes = 0

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
            if self.level_idx + 1 < len(self._LEVELS):
                self.level_idx += 1
                self._start_level(self.level_idx)
            else:
                self.won = True
                self.game_over = True

    def draw(self):
        off_y = max(1, (self.h - self.rows - 3) // 2)
        off_x = max(0, (self.w - self.cols) // 2)
        header = (f' SOKOBAN  Level {self.level_idx + 1}/{len(self._LEVELS)}'
                  f'  Moves:{self.moves}  Pushes:{self.pushes} ')
        self.safe_addstr(off_y - 1, max(0, (self.w - len(header)) // 2),
                         header, curses.A_BOLD)
        for r in range(self.rows):
            for c in range(self.cols):
                cell = (r, c)
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
                ('Moves', self.moves), ('Pushes', self.pushes)]

    def get_save_data(self):
        return {'level': self.level_idx, 'boxes': [list(b) for b in self.boxes],
                'py': self.py, 'px': self.px, 'moves': self.moves,
                'pushes': self.pushes, 'score': self.score}
