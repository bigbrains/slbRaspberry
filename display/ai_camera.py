import logging
import os
import subprocess
from datetime import datetime

from PIL import Image, ImageDraw
from display.menu import _load_font, ST7789Driver

log = logging.getLogger(__name__)

CAMERA_DEVICE = "/dev/video0"   # USB camera — change if needed
PHOTO_DIR     = "/home/pi/slb/photos"


class AICamera:
    """
    Captures a photo from a USB camera and displays it on the ST7789 240×240 screen.
    Uses fswebcam for capture and PIL for resize/display.
    Saves each photo to PHOTO_DIR with a timestamped filename.
    """

    W = 240
    H = 240

    C_BG      = (0,   0,   0)
    C_MSG_FG  = (220, 220, 220)
    C_ERR_FG  = (255,  80,  80)
    C_HDR_BG  = (25,  80,  160)
    C_HDR_FG  = (255, 255, 255)
    HEADER_H  = 22

    def __init__(self, device: str = CAMERA_DEVICE, photo_dir: str = PHOTO_DIR):
        self.device    = device
        self.photo_dir = photo_dir
        os.makedirs(self.photo_dir, exist_ok=True)
        self._font   = _load_font(12)
        self._font_s = _load_font(10)

    # ── Public ────────────────────────────────────────────────────────────────

    def capture_and_display(self, driver: ST7789Driver) -> str | None:
        """Capture one frame, save it, push it to the display. Returns saved path or None."""
        self._show_message(driver, "Capturing...")
        try:
            img, path = self._capture()
            log.info("Captured %dx%d → %s", img.width, img.height, path)
            driver.blit(self._fit(img))
            return path
        except CameraError as e:
            log.error("Camera error: %s", e)
            self._show_error(driver, str(e))
            return None

    def capture(self) -> tuple[Image.Image, str]:
        """Capture, save, and return (fitted_240x240_image, path). Raises CameraError."""
        img, path = self._capture()
        return self._fit(img), path

    def is_available(self) -> bool:
        return os.path.exists(self.device)

    # ── Capture ───────────────────────────────────────────────────────────────

    def _capture(self) -> tuple[Image.Image, str]:
        if not self.is_available():
            raise CameraError(f"No camera at {self.device}")

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.photo_dir, f"photo_{ts}.jpg")

        result = subprocess.run(
            ["fswebcam", "-d", self.device,
             "-r", "3264x2448", "--no-banner", "--quiet",
             "--skip", "10",      # skip 10 frames so camera auto-exposes
             "--jpeg", "95",      # JPEG quality 0-100
             path],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            raise CameraError(result.stderr.decode().strip() or "fswebcam failed")

        img = Image.open(path)
        img.load()   # force read before returning (file stays on disk)
        return img, path

    # ── Image processing ──────────────────────────────────────────────────────

    def _fit(self, img: Image.Image) -> Image.Image:
        """Centre-crop to square then resize to 240×240."""
        w, h  = img.size
        side  = min(w, h)
        left  = (w - side) // 2
        top   = (h - side) // 2
        img   = img.crop((left, top, left + side, top + side))
        return img.resize((self.W, self.H), Image.LANCZOS)

    # ── On-screen messages ────────────────────────────────────────────────────

    def _show_message(self, driver: ST7789Driver, text: str):
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.text((6, 5), "AI Camera", font=self._font, fill=self.C_HDR_FG)
        d.text((10, self.H // 2 - 8), text, font=self._font, fill=self.C_MSG_FG)
        driver.blit(img)

    def _show_error(self, driver: ST7789Driver, msg: str):
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.text((6, 5), "AI Camera", font=self._font, fill=self.C_HDR_FG)
        d.text((6, self.HEADER_H + 8),  "Camera error:", font=self._font,   fill=self.C_ERR_FG)
        d.text((6, self.HEADER_H + 26), msg,             font=self._font_s, fill=self.C_MSG_FG)
        driver.blit(img)


class CameraError(Exception):
    pass
