import time
import spidev
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _pil_to_565(img: Image.Image) -> bytes:
    """Convert PIL RGB image → raw RGB565 bytes (big-endian, SPI-ready)."""
    try:
        import numpy as np
        arr = np.array(img.convert("RGB"), dtype=np.uint16)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        color = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        hi = ((color >> 8) & 0xFF).astype(np.uint8)
        lo = (color & 0xFF).astype(np.uint8)
        return bytes(np.stack([hi, lo], axis=-1).flatten())
    except ImportError:
        buf = bytearray(img.width * img.height * 2)
        idx = 0
        for r, g, b in img.convert("RGB").getdata():
            c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            buf[idx]     = (c >> 8) & 0xFF
            buf[idx + 1] = c & 0xFF
            idx += 2
        return bytes(buf)


# ── Display driver ────────────────────────────────────────────────────────────

class ST7789Driver:
    """Minimal raw-SPI driver for the ST7789 240×240 display."""

    W = 240
    H = 240

    def __init__(self, dc_pin: int = 24, rst_pin: int = 25, speed: int = 4_000_000):
        self._dc  = dc_pin
        self._rst = rst_pin

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self._dc,  GPIO.OUT)
        GPIO.setup(self._rst, GPIO.OUT)

        self._spi = spidev.SpiDev()
        self._spi.open(0, 0)
        self._spi.max_speed_hz = speed
        self._spi.mode = 0

        self._init()

    def _cmd(self, c: int):
        GPIO.output(self._dc, 0)
        self._spi.writebytes([c])

    def _data(self, b: bytes):
        GPIO.output(self._dc, 1)
        for i in range(0, len(b), 4096):
            self._spi.writebytes(list(b[i:i + 4096]))

    def _init(self):
        GPIO.output(self._rst, 0); time.sleep(0.05)
        GPIO.output(self._rst, 1); time.sleep(0.12)
        self._cmd(0x01); time.sleep(0.15)     # SWRESET
        self._cmd(0x11); time.sleep(0.15)     # SLPOUT
        self._cmd(0x3A); self._data(b'\x55')  # 16-bit colour
        self._cmd(0x36); self._data(b'\x60')  # MADCTL – 90° CW
        self._cmd(0x21)                        # INVON
        self._cmd(0x29); time.sleep(0.1)      # DISPON

    def _window(self, x0: int, y0: int, x1: int, y1: int):
        self._cmd(0x2A)
        self._data(bytes([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
        self._cmd(0x2B)
        self._data(bytes([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
        self._cmd(0x2C)

    def blit(self, img: Image.Image):
        """Push a 240×240 PIL image to the display."""
        self._window(0, 0, self.W - 1, self.H - 1)
        self._data(_pil_to_565(img))

    def close(self):
        self._spi.close()
        GPIO.cleanup()


# ── Menu ─────────────────────────────────────────────────────────────────────

class Menu:
    """
    Scrollable menu for a 240×240 ST7789 display.

    `items` is a dict:
        key   – label shown on screen (str)
        value – class associated with that option (type)

    Example:
        items = {
            "WiFi Settings":   WiFiSettings,
            "Bluetooth":       BluetoothSettings,
            "Reboot":          RebootAction,
        }
        menu = Menu(items, title="SETTINGS")
        menu.render(driver)

        menu.down()
        menu.render(driver)

        label, cls = menu.select()   # returns ("Bluetooth", BluetoothSettings)
    """

    W        = 240
    H        = 240
    ITEM_H   = 20   # px per row
    HEADER_H = 28   # px for title bar
    SB_W     = 10   # scrollbar width

    C_BG       = (10,  10,  10)
    C_FG       = (210, 210, 210)
    C_HDR_BG   = (25,  80,  160)
    C_HDR_FG   = (255, 255, 255)
    C_SEL_BG   = (0,   150, 75)
    C_SEL_FG   = (255, 255, 255)
    C_DIVIDER  = (45,  45,  45)
    C_SB_TRACK = (28,  28,  28)
    C_SB_THUMB = (110, 110, 110)

    def __init__(self, items: dict[str, type], title: str = "MENU"):
        if not items:
            raise ValueError("items dict must not be empty")
        self.items    = items                      # preserves insertion order (Python 3.7+)
        self._keys    = list(items.keys())         # ordered label list for indexing
        self.title    = title
        self.selected = 0
        self.offset   = 0
        self.visible  = (self.H - self.HEADER_H) // self.ITEM_H

        self._font_hdr  = _load_font(15)
        self._font_item = _load_font(13)

    # ── Navigation ───────────────────────────────────────────────────────────

    def up(self) -> bool:
        """Move selection one item up, wrapping to last item at the top."""
        if self.selected > 0:
            self.selected -= 1
            if self.selected < self.offset:
                self.offset -= 1
        else:
            self.selected = len(self._keys) - 1
            self.offset = max(0, self.selected - self.visible + 1)
        return True

    def down(self) -> bool:
        """Move selection one item down, wrapping to first item at the bottom."""
        if self.selected < len(self._keys) - 1:
            self.selected += 1
            if self.selected >= self.offset + self.visible:
                self.offset += 1
        else:
            self.selected = 0
            self.offset = 0
        return True

    def select(self) -> tuple[str, type]:
        """Return (label, class) for the currently highlighted item."""
        label = self._keys[self.selected]
        return label, self.items[label]

    # ── Rendering ────────────────────────────────────────────────────────────

    def render(self, driver: ST7789Driver):
        """Build the frame and push it to the display."""
        driver.blit(self._build_frame())

    def _build_frame(self) -> Image.Image:
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        self._draw_header(d)
        self._draw_items(d)
        self._draw_scrollbar(d)
        return img

    def _draw_header(self, d: ImageDraw.Draw):
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.text((10, 7), self.title, font=self._font_hdr, fill=self.C_HDR_FG)
        counter = f"{self.selected + 1}/{len(self._keys)}"
        d.text((self.W - self.SB_W - 46, 9), counter,
               font=self._font_item, fill=self.C_HDR_FG)

    def _draw_items(self, d: ImageDraw.Draw):
        content_w = self.W - self.SB_W - 1
        for i in range(self.visible):
            idx = self.offset + i
            if idx >= len(self._keys):
                break
            y      = self.HEADER_H + i * self.ITEM_H
            is_sel = idx == self.selected
            bg     = self.C_SEL_BG if is_sel else self.C_BG
            fg     = self.C_SEL_FG if is_sel else self.C_FG

            d.rectangle((0, y, content_w, y + self.ITEM_H - 1), fill=bg)
            prefix = ">" if is_sel else " "
            d.text((6, y + 4), f"{prefix} {self._keys[idx]}",
                   font=self._font_item, fill=fg)

            if not is_sel:
                d.line((4, y + self.ITEM_H - 1, content_w - 4, y + self.ITEM_H - 1),
                       fill=self.C_DIVIDER)

    def _draw_scrollbar(self, d: ImageDraw.Draw):
        if len(self._keys) <= self.visible:
            return
        sb_x      = self.W - self.SB_W
        track_top = self.HEADER_H
        track_h   = self.H - track_top
        d.rectangle((sb_x, track_top, self.W - 1, self.H - 1), fill=self.C_SB_TRACK)

        thumb_h = max(14, track_h * self.visible // len(self._keys))
        max_off = len(self._keys) - self.visible
        thumb_y = track_top + (track_h - thumb_h) * self.offset // max(1, max_off)
        d.rectangle((sb_x + 2, thumb_y, self.W - 3, thumb_y + thumb_h),
                    fill=self.C_SB_THUMB)
