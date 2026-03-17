"""
display/qa_result.py — Renders Q&A results from API response.

Data format: [{question: str, correctAnswers: [str, ...]}]
Packs as many Q&A items as fit per page, numbered, paginated.
Each answer is rendered on its own line in a distinct colour.
"""
from PIL import Image, ImageDraw
from display.menu import _load_font, ST7789Driver

W, H = 240, 240

C_BG  = (0,   0,   0)
C_Q   = (255, 255, 255)    # question — white
C_A   = (80,  220,  80)    # answer   — green
C_NUM = (160, 160, 160)    # index number — grey
C_SEP = (120, 120, 120)    # separator line
C_PG  = (100, 100, 100)    # page counter


class QAResultView:

    PAD    = 10
    NUM_W  = 18
    LINE_Q = 18
    LINE_A = 15
    SEP_H  = 10
    BOTTOM = 16   # reserved for page counter

    def __init__(self, data: list[dict]):
        self._fq   = _load_font(13)
        self._fa   = _load_font(11)
        self._fnum = _load_font(10)
        self._fpg  = _load_font(10)
        self._tw   = W - self.PAD - self.NUM_W - 6 - self.PAD
        self._items  = self._parse(data)   # list of (q: str, answers: list[str])
        self._pages  = self._paginate()
        self.page    = 0

    # ── Parse ─────────────────────────────────────────────────────────────────

    def _parse(self, data) -> list[tuple[str, list[str]]]:
        items = []
        if not isinstance(data, list):
            return items
        for item in data:
            q       = item.get("question", "")
            answers = [str(x) for x in item.get("correctAnswers", []) if x]
            items.append((q, answers))
        return items

    # ── Layout ────────────────────────────────────────────────────────────────

    def _wrap(self, text: str, font) -> list[str]:
        words = text.split()
        lines, line = [], ""
        for w in words:
            c = f"{line} {w}".strip()
            try:
                cw = font.getlength(c)
            except AttributeError:
                cw = font.getbbox(c)[2]
            if cw <= self._tw:
                line = c
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
        return lines or [""]

    def _item_h(self, q: str, answers: list[str]) -> int:
        h = len(self._wrap(q, self._fq)) * self.LINE_Q
        for a in answers:
            h += len(self._wrap(a, self._fa)) * self.LINE_A
        h += self.SEP_H
        return h

    def _paginate(self) -> list[list[int]]:
        pages, cur, used = [], [], 0
        for i, (q, answers) in enumerate(self._items):
            h       = self._item_h(q, answers)
            reserve = self.BOTTOM if cur else 0
            if cur and used + h + reserve > H - self.PAD:
                pages.append(cur)
                cur, used = [i], h
            else:
                cur.append(i)
                used += h
        if cur:
            pages.append(cur)
        return pages or [[]]

    # ── Navigation ────────────────────────────────────────────────────────────

    def next_page(self) -> bool:
        if self.page < len(self._pages) - 1:
            self.page += 1
            return True
        return False

    def prev_page(self) -> bool:
        if self.page > 0:
            self.page -= 1
            return True
        return False

    def total_pages(self) -> int:
        return len(self._pages)

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self, driver: ST7789Driver):
        driver.blit(self._build())

    def _build(self) -> Image.Image:
        img = Image.new("RGB", (W, H), C_BG)
        d   = ImageDraw.Draw(img)

        if not self._items:
            d.text((self.PAD, self.PAD), "No results", font=self._fq, fill=C_Q)
            return img

        indices = self._pages[self.page]
        y = self.PAD

        for idx in indices:
            q, answers = self._items[idx]
            num = str(idx + 1)

            # number
            try:
                nw = self._fnum.getlength(num)
            except AttributeError:
                nw = self._fnum.getbbox(num)[2]
            d.text((self.PAD + (self.NUM_W - nw) // 2, y + 2),
                   num, font=self._fnum, fill=C_NUM)

            tx = self.PAD + self.NUM_W + 6

            # question
            for line in self._wrap(q, self._fq):
                d.text((tx, y), line, font=self._fq, fill=C_Q)
                y += self.LINE_Q

            # each answer on its own line
            for a in answers:
                for line in self._wrap(a, self._fa):
                    d.text((tx, y), line, font=self._fa, fill=C_A)
                    y += self.LINE_A

            y += 4

            # separator (not after last on page)
            if idx != indices[-1]:
                d.rectangle((self.PAD, y, W - self.PAD, y + 1), fill=C_SEP)
                y += self.SEP_H - 4

        # page counter
        if len(self._pages) > 1:
            pg = f"{self.page + 1} / {len(self._pages)}"
            try:
                pw = self._fpg.getlength(pg)
            except AttributeError:
                pw = self._fpg.getbbox(pg)[2]
            d.text(((W - pw) // 2, H - 12), pg, font=self._fpg, fill=C_PG)

        return img
