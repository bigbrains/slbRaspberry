from PIL import Image, ImageDraw
from display.menu import _load_font, ST7789Driver


class SimpleQuestions:
    """
    Renders Q&A pairs on the 240x240 display.
    Automatically calculates how many pairs fit per page based on
    actual character width and text wrapping.
    """

    W = 240
    H = 240
    PAD       = 4
    HEADER_H  = 24
    LINE_H    = 15   # px per text line

    C_BG      = (10,  10,  10)
    C_HDR_BG  = (25,  80,  160)
    C_HDR_FG  = (255, 255, 255)
    C_Q       = (100, 200, 255)   # question — light blue
    C_A       = (140, 220, 140)   # answer   — light green
    C_SEP     = (45,  45,  45)

    QUESTIONS: dict[str, str] = {
        "What is Python?":
            "High-level interpreted programming language known for readability.",
        "What is GPIO?":
            "General Purpose Input/Output — programmable pins on the Pi.",
        "What is SPI?":
            "Serial Peripheral Interface — fast 4-wire communication protocol.",
        "What is I2C?":
            "Inter-Integrated Circuit — 2-wire protocol for short-distance comms.",
        "What is RAM?":
            "Random Access Memory — fast volatile storage used while running.",
        "What is a CPU?":
            "Central Processing Unit — executes program instructions.",
        "What is SSH?":
            "Secure Shell — encrypted protocol for remote terminal access.",
        "What is Linux?":
            "Open-source Unix-like OS kernel used by Raspberry Pi OS.",
        "What is PWM?":
            "Pulse Width Modulation — simulates analog output via digital pin.",
        "What is an OS?":
            "Operating System — manages hardware and runs applications.",
    }

    def __init__(self):
        self._font_hdr  = _load_font(13)
        self._font      = _load_font(11)
        self._chars_per_line = self._measure_chars_per_line()
        self._avail_lines    = (self.H - self.HEADER_H) // self.LINE_H
        self._pages = self._paginate()
        self.page   = 0

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _measure_chars_per_line(self) -> int:
        """Use PIL to measure real character width for the chosen font."""
        try:
            w = self._font.getlength("M")
        except AttributeError:
            bbox = self._font.getbbox("M")
            w = bbox[2] - bbox[0]
        usable = self.W - self.PAD * 2
        return max(10, int(usable // w))

    def _wrap(self, text: str, prefix: str) -> list[str]:
        """Word-wrap text to fit within chars_per_line, with a prefix on line 1."""
        words  = text.split()
        lines  = []
        line   = prefix
        indent = " " * len(prefix)
        for word in words:
            if len(line) + len(word) + (1 if line != prefix and line != indent else 0) \
                    <= self._chars_per_line:
                if line in (prefix, indent):
                    line += word
                else:
                    line += " " + word
            else:
                lines.append(line)
                line = indent + word
        if line:
            lines.append(line)
        return lines

    def _paginate(self) -> list[list[tuple]]:
        """Split Q&A pairs into pages based on available screen lines."""
        pages, cur, used = [], [], 0
        for q, a in self.QUESTIONS.items():
            q_lines = self._wrap(q, "Q: ")
            a_lines = self._wrap(a, "A: ")
            needed  = len(q_lines) + len(a_lines) + 1   # +1 for separator gap
            if used + needed > self._avail_lines and cur:
                pages.append(cur)
                cur, used = [], 0
            cur.append((q_lines, a_lines))
            used += needed
        if cur:
            pages.append(cur)
        return pages

    # ── Navigation ───────────────────────────────────────────────────────────

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

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self, driver: ST7789Driver):
        driver.blit(self._build_frame())

    def _build_frame(self) -> Image.Image:
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)

        # Header
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.text((self.PAD, 6), "Simple Questions", font=self._font_hdr, fill=self.C_HDR_FG)
        if self._pages:
            pg = f"{self.page + 1}/{len(self._pages)}"
            d.text((self.W - 34, 7), pg, font=self._font, fill=self.C_HDR_FG)

        if not self._pages:
            d.text((self.PAD, self.HEADER_H + 8), "No questions loaded.",
                   font=self._font, fill=self.C_A)
            return img

        # Calculate total height used by this page's content
        pairs = self._pages[self.page]
        total_lines = sum(len(q) + len(a) + 1 for q, a in pairs) - 1  # no trailing sep
        content_h   = total_lines * self.LINE_H

        # Vertically centre within the area below the header
        available = self.H - self.HEADER_H
        top_pad   = max(3, (available - content_h) // 2)
        y = self.HEADER_H + top_pad

        for i, (q_lines, a_lines) in enumerate(pairs):
            for line in q_lines:
                d.text((self.PAD, y), line, font=self._font, fill=self.C_Q)
                y += self.LINE_H
            for line in a_lines:
                d.text((self.PAD, y), line, font=self._font, fill=self.C_A)
                y += self.LINE_H
            # Separator between pairs (not after the last one)
            if i < len(pairs) - 1:
                d.line((self.PAD, y + 2, self.W - self.PAD, y + 2), fill=self.C_SEP)
                y += self.LINE_H

        return img
