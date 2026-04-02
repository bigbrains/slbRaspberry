"""Show block_1.png then block_2.png on the ST7789 display."""
import time
from PIL import Image
from display.menu import ST7789Driver

IMAGES = ["block_1.png", "block_2.png"]
DISPLAY_SIZE = (240, 240)

driver = ST7789Driver()

for path in IMAGES:
    img = Image.open(path).convert("RGB").resize(DISPLAY_SIZE)
    driver.blit(img)
    print(f"Showing {path} — press Ctrl+C to exit or wait 5s")
    time.sleep(5)

print("Done.")
