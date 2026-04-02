"""
display/qa_result.py — Renders Q&A results from API response.

Data format: [{question: str, correctAnswers: [str, ...]}]
Packs as many Q&A items as fit per page, numbered, paginated.
Each answer is rendered on its own line in a distinct colour.
"""
from PIL import Image, ImageDraw
from display.menu import _load_font, ST7789Driver

W, H     = 240, 240
HDR_H    = 24

C_BG     = (4,   4,   8)
C_HDR_BG = (10,  16,  32)
C_HDR_FG = (255, 255, 255)
C_Q      = (225, 228, 238)   # question — near-white
C_NUM    = (65,  75, 100)    # index number — muted blue-grey
C_SEP    = (26,  30,  45)    # separator between items
C_SEP_QA = (18,  22,  35)    # separator between question and answers
C_SEP_AA = (14,  16,  26)    # separator between individual answers
C_PG     = (48,  55,  75)    # page counter

# Rotating palette for correct answers — each answer gets a distinct colour
C_ANSWERS = [
    (75,  220,  90),   # green
    (90,  175, 255),   # blue
    (250, 205,  55),   # yellow
    (255, 110, 110),   # red
    (185,  90, 255),   # purple
    (55,  215, 195),   # cyan
    (255, 155,  60),   # orange
]


class QAResultView:

    PAD    = 10
    NUM_W  = 18
    LINE_Q = 17
    LINE_A = 14
    SEP_H  = 8
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
        h += 6   # separator between question and answers
        for i, a in enumerate(answers):
            if i > 0:
                h += 5  # separator between answers
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

        # Header
        d.rectangle((0, 0, W - 1, HDR_H - 1), fill=C_HDR_BG)
        d.line((0, HDR_H - 1, W - 1, HDR_H - 1), fill=(28, 40, 70))
        d.text((8, 6), "Results", font=self._fq, fill=C_HDR_FG)
        if len(self._pages) > 1:
            pg = f"{self.page + 1}/{len(self._pages)}"
            try:
                pw = int(self._fpg.getlength(pg))
            except AttributeError:
                pw = self._fpg.getbbox(pg)[2]
            px = W - pw - 10
            d.rectangle((px - 4, 6, px + pw + 4, HDR_H - 6), fill=(20, 28, 55))
            d.text((px, 7), pg, font=self._fpg, fill=(85, 105, 165))

        if not self._items:
            d.text((self.PAD, HDR_H + 10), "No results", font=self._fq, fill=C_Q)
            return img

        indices = self._pages[self.page]
        y = HDR_H + 6

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

            # line between question and answers
            y += 2
            d.rectangle((tx, y, W - self.PAD, y), fill=C_SEP_QA)
            y += 4

            # each answer separated by a line, each in its own colour
            for i, a in enumerate(answers):
                if i > 0:
                    d.rectangle((tx + 4, y, W - self.PAD, y), fill=C_SEP_AA)
                    y += 5
                color = C_ANSWERS[i % len(C_ANSWERS)]
                for line in self._wrap(a, self._fa):
                    d.text((tx, y), line, font=self._fa, fill=color)
                    y += self.LINE_A

            y += 4

            # separator (not after last on page)
            if idx != indices[-1]:
                d.rectangle((self.PAD, y, W - self.PAD, y + 1), fill=C_SEP)
                y += self.SEP_H - 4

        # page counter (bottom) — only when multiple pages, as subtle hint
        if len(self._pages) > 1:
            pg = f"▲▼ page {self.page + 1}/{len(self._pages)}"
            try:
                pw = self._fpg.getlength(pg)
            except AttributeError:
                pw = self._fpg.getbbox(pg)[2]
            d.text(((W - pw) // 2, H - 12), pg, font=self._fpg, fill=C_PG)

        return img
