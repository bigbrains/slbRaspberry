import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont
from adafruit_rgb_display import st7789


class DisplayService:
    WIDTH = 240
    HEIGHT = 240

    def __init__(self):
        spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)
        cs = digitalio.DigitalInOut(board.CE0)
        dc = digitalio.DigitalInOut(board.D24)
        reset = digitalio.DigitalInOut(board.D25)

        self.display = st7789.ST7789(
            spi,
            cs=cs,
            dc=dc,
            rst=reset,
            width=self.WIDTH,
            height=self.HEIGHT,
            y_offset=80,
            rotation=0,
        )

        self._image = Image.new("RGB", (self.WIDTH, self.HEIGHT), "BLACK")
        self._draw = ImageDraw.Draw(self._image)
        self._font = ImageFont.load_default()

    def print_line(self, text: str):
        self._draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), fill="black")
        self._draw.text((10, self.HEIGHT // 2 - 8), text, font=self._font, fill="white")
        self.display.image(self._image)

    def clear(self):
        self._draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), fill="black")
        self.display.image(self._image)
