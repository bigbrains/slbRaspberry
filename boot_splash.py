"""
boot_splash.py — boot animation for the ST7789 240×240 display.
Shows a spinner until killed by the menu_show service.
Run as: sudo .venv/bin/python boot_splash.py
"""
import sys
import time

SPINNER = ['|', '/', '-', '\\']

def _load_font(size):
    from PIL import ImageFont
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def main():
    import spidev  # noqa — ensure SPI available before importing driver
    from display.menu import ST7789Driver
    from PIL import Image, ImageDraw

    driver = ST7789Driver()
    W, H   = 240, 240

    font_title  = _load_font(36)
    font_sub    = _load_font(16)
    font_spin   = _load_font(28)

    i = 0
    while True:
        img = Image.new("RGB", (W, H), (10, 10, 10))
        d   = ImageDraw.Draw(img)

        # Title
        d.text((W // 2, 80), "SLB", font=font_title, fill=(255, 255, 255), anchor="mm")

        # Subtitle
        d.text((W // 2, 118), "Starting up...", font=font_sub, fill=(140, 160, 200), anchor="mm")

        # Spinner
        d.text((W // 2, 160), SPINNER[i % len(SPINNER)], font=font_spin,
               fill=(25, 80, 160), anchor="mm")

        driver.blit(img)
        i += 1
        time.sleep(0.15)


if __name__ == "__main__":
    import os
    os.chdir("/home/pi/slb")
    main()
