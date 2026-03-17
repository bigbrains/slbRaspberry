"""
ui_demo.py — Q&A compact list UI: pack as many as fit, numbered, paginated.
Run: python3 ui_demo.py
"""
import subprocess
from PIL import Image, ImageDraw, ImageFont

W, H = 240, 240

C_BG         = (0,    0,   0)
C_NUM_BG     = (0,    0,   0)
C_NUM_FG     = (255, 255, 255)
C_Q_TEXT     = (255, 255, 255)
C_A_TEXT     = (255, 255, 255)
C_SEP        = (255, 255, 255)
C_PG         = (100, 100, 100)


def _font(size: int):
    for path in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _tw(font, text):
    try:
        return int(font.getlength(text))
    except AttributeError:
        return font.getbbox(text)[2]


def _wrap(text, font, max_px):
    words = text.split()
    lines, line = [], ""
    for w in words:
        c = f"{line} {w}".strip()
        if _tw(font, c) <= max_px:
            line = c
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines or [""]


# ── Measure how many items fit in available height ────────────────────────────

def measure_items(questions, f_q, f_a, text_w, line_q, line_a, sep):
    """Return list of item heights (px) for each question."""
    heights = []
    for q, a in questions:
        q_h = len(_wrap(q, f_q, text_w)) * line_q
        a_h = len(_wrap(a, f_a, text_w)) * line_a
        heights.append(q_h + a_h + sep)
    return heights


def paginate(item_heights, avail_h, bottom_reserve):
    """Split items into pages so each page fits avail_h.
    bottom_reserve is subtracted only when there are multiple pages (for page counter)."""
    pages = []
    cur, used = [], 0
    for i, h in enumerate(item_heights):
        fits = avail_h if len(pages) == 0 and not cur else avail_h - bottom_reserve
        if used + h <= (avail_h if not cur else avail_h - bottom_reserve):
            cur.append(i)
            used += h
        else:
            pages.append(cur)
            cur, used = [i], h
    if cur:
        pages.append(cur)
    return pages


def render_page(questions, indices, page, total_pages,
                f_q, f_a, f_num, f_pg,
                line_q, line_a, sep, pad, num_w, text_w, avail_h) -> Image.Image:
    img = Image.new("RGB", (W, H), C_BG)
    d   = ImageDraw.Draw(img)

    y = pad
    for idx in indices:
        q, a = questions[idx]
        num  = str(idx + 1)

        # number badge
        try:
            d.rounded_rectangle((pad, y + 2, pad + num_w, y + 2 + 16),
                                 radius=3, fill=C_NUM_BG)
        except AttributeError:
            d.rectangle((pad, y + 2, pad + num_w, y + 2 + 16), fill=C_NUM_BG)
        nw = _tw(f_num, num)
        d.text((pad + (num_w - nw) // 2, y + 3), num, font=f_num, fill=C_NUM_FG)

        tx = pad + num_w + 6

        # question
        for line in _wrap(q, f_q, text_w):
            d.text((tx, y), line, font=f_q, fill=C_Q_TEXT)
            y += line_q

        # answer
        for line in _wrap(a, f_a, text_w):
            d.text((tx, y), line, font=f_a, fill=C_A_TEXT)
            y += line_a

        y += 4   # gap before separator

        # separator (skip after last item)
        if idx != indices[-1]:
            d.rectangle((pad, y, W - pad, y + 1), fill=C_SEP)
            y += sep - 4

    # page counter (only if multiple pages)
    if total_pages > 1:
        pg = f"{page} / {total_pages}"
        d.text(((W - _tw(f_pg, pg)) // 2, H - 12), pg, font=f_pg, fill=C_PG)

    return img


def build_all_pages(questions) -> list[Image.Image]:
    PAD      = 10
    NUM_W    = 18
    LINE_Q   = 18
    LINE_A   = 15
    SEP_H    = 10    # space between items (separator line + gap)
    BOTTOM   = 16   # reserved for page counter
    TEXT_W   = W - PAD - NUM_W - 6 - PAD

    f_q   = _font(13)
    f_a   = _font(11)
    f_num = _font(10)
    f_pg  = _font(10)

    item_h = measure_items(questions, f_q, f_a, TEXT_W, LINE_Q, LINE_A, SEP_H)

    # simple greedy paging
    pages_idx = []
    cur, used = [], 0
    for i, h in enumerate(item_h):
        reserve = BOTTOM if (used + h > H - PAD) else 0
        if cur and used + h + reserve > H - PAD:
            pages_idx.append(cur)
            cur, used = [i], h
        else:
            cur.append(i)
            used += h
    if cur:
        pages_idx.append(cur)

    total_pages = len(pages_idx)
    return [
        render_page(questions, idx_list, p + 1, total_pages,
                    f_q, f_a, f_num, f_pg,
                    LINE_Q, LINE_A, SEP_H, PAD, NUM_W, TEXT_W, H - PAD)
        for p, idx_list in enumerate(pages_idx)
    ]


QUESTIONS = [
    ("What is Python?",
     "High-level interpreted language known for readability."),
    ("What does GPIO stand for?",
     "General Purpose Input/Output — programmable pins."),
    ("What is SPI?",
     "Fast 4-wire synchronous serial bus."),
    ("What is I2C?",
     "2-wire protocol for short-distance comms."),
    ("What is RAM?",
     "Fast volatile working memory."),
    ("What is SSH?",
     "Encrypted protocol for remote terminal access."),
    ("What is PWM?",
     "Simulates analog output via digital pin toggling."),
    ("What is Linux?",
     "Open-source OS kernel used by Raspberry Pi OS."),
]

if __name__ == "__main__":
    pages = build_all_pages(QUESTIONS)
    print(f"{len(QUESTIONS)} questions → {len(pages)} page(s)")

    GAP = 6
    out_img = Image.new("RGB", (W * len(pages) + GAP * (len(pages) - 1), H), (3, 4, 8))
    for i, p in enumerate(pages):
        out_img.paste(p, (i * (W + GAP), 0))

    out = "/tmp/qa_ui_preview.png"
    out_img.save(out)
    print(f"Saved → {out}")
    subprocess.run(["open", out])
