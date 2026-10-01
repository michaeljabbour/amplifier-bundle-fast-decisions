class BowlingGame:
    def __init__(self):
        self._rolls = []
    def _frames_raw(self):
        frames, cur, i = [], [], 0
        for r in self._rolls:
            cur.append(r)
            n = len(frames) + 1
            if n < 10:
                if r == 10 or len(cur) == 2:
                    frames.append(cur); cur = []
            else:
                pass
        if cur: frames.append(cur)
        return frames
    def frames(self):
        return [list(f) for f in self._frames_raw()]
    def roll(self, pins):
        if isinstance(pins, bool) or not isinstance(pins, int):
            raise TypeError("pins must be int")
        if pins < 0 or pins > 10:
            raise ValueError("bad pins")
        fr = self._frames_raw()
        if self._complete(fr):
            raise IndexError("game over")
        # frame validation
        cur = fr[-1] if fr and not self._frame_done(fr, len(fr)) else []
        n = len(fr) if cur else len(fr) + 1
        if n < 10:
            if len(cur) == 1 and cur[0] + pins > 10:
                raise ValueError("frame > 10")
        else:
            if len(cur) == 1 and cur[0] != 10 and cur[0] + pins > 10:
                raise ValueError("frame > 10")
            if len(cur) == 2 and cur[0] == 10 and cur[1] != 10 and cur[1] + pins > 10:
                raise ValueError("fill > 10")
        self._rolls.append(pins)
    def _frame_done(self, fr, n):
        f = fr[n - 1]
        if n < 10:
            return f[0] == 10 or len(f) == 2
        return self._tenth_done(f)
    @staticmethod
    def _tenth_done(f):
        if len(f) == 3: return True
        if len(f) == 2 and f[0] + f[1] < 10: return True
        return False
    def _complete(self, fr):
        return len(fr) == 10 and self._tenth_done(fr[9])
    def _score_upto(self, upper=None):
        r, total, i, out = self._rolls, 0, 0, []
        for frame in range(10):
            if i >= len(r): break
            if r[i] == 10:
                if i + 2 >= len(r): break
                total += 10 + r[i+1] + r[i+2]; i += 1
            else:
                if i + 1 >= len(r): break
                if r[i] + r[i+1] == 10:
                    if i + 2 >= len(r): break
                    total += 10 + r[i+2]
                else:
                    total += r[i] + r[i+1]
                i += 2
            out.append(total)
        return out
    def frame_scores(self):
        return self._score_upto()
    def score(self):
        fr = self._frames_raw()
        if not self._complete(fr):
            raise IndexError("incomplete")
        return self._score_upto()[-1]
