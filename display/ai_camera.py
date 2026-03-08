import json
import logging
import os
import subprocess
import time
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

    Also handles scenario fetching from /api/sessions and photo submission
    to /api/solve.
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

    # ── API ───────────────────────────────────────────────────────────────────

    def fetch_scenarios(self, api_base: str) -> list[dict]:
        """GET /api/sessions → list of scenario dicts with at least {id, ...}."""
        url = f"{api_base}/api/sessions/scenarios"
        log.info("fetch_scenarios: GET %s", url)
        try:
            import requests
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            log.info("fetch_scenarios: got %d scenarios", len(data))
            return data
        except Exception as e:
            log.error("fetch_scenarios failed: %s", e)
            raise CameraError(f"fetch_scenarios: {e}")

    def poll_data_check(self, api_base: str, session_id: int, version) -> tuple:
        """GET /api/data/check?sessionId=X&version=Y
        Returns (has_update, new_version, data). Raises CameraError on failure."""
        url = f"{api_base}/api/data/check?sessionId={session_id}&version={version}"
        log.debug("poll_data_check: GET %s", url)
        try:
            import requests
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            d = resp.json()
            if d.get("hasUpdate"):
                return True, d.get("version"), d.get("data")
            return False, None, None
        except Exception as e:
            raise CameraError(f"poll: {e}")

    def submit_photo(self, api_base: str, scenario_id: int, photo_path: str) -> dict:
        """POST /api/solve with scenarioId and photos[]. Returns parsed JSON response."""
        url = f"{api_base}/api/solve"
        log.info("submit_photo: POST %s  scenario=%s  file=%s", url, scenario_id,
                 os.path.basename(photo_path))
        try:
            import requests
            with open(photo_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={"scenarioId": scenario_id},
                    files={"photos[]": (os.path.basename(photo_path), f, "image/jpeg")},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                log.info("submit_photo: response %s", data)
                return data
        except Exception as e:
            log.error("submit_photo failed: %s", e)
            raise CameraError(f"submit_photo: {e}")

    # ── Scenario / camera screens ─────────────────────────────────────────────

    def show_camera_ready(self, driver: ST7789Driver, scenario_name: str):
        """Show camera-ready screen with scenario name and button hints."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.text((6, 5), "AI Camera", font=self._font, fill=self.C_HDR_FG)

        y = self.HEADER_H + 10
        d.text((6, y), "Scenario:", font=self._font_s, fill=(150, 150, 150))
        y += 16
        for line in self._wrap(scenario_name, 28):
            d.text((6, y), line, font=self._font, fill=(100, 200, 255))
            y += 17

        y = max(y + 14, self.HEADER_H + 100)
        d.line((6, y - 6, self.W - 6, y - 6), fill=(40, 40, 40))
        d.text((6, y),      "B    — capture & submit", font=self._font_s, fill=self.C_MSG_FG)
        d.text((6, y + 16), "LEFT — back to menu",     font=self._font_s, fill=(90, 90, 90))
        driver.blit(img)

    def show_response(self, driver: ST7789Driver, response: dict, duration: float = 5.0):
        """Display API response on screen for duration seconds, then return."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)

        success   = response.get("success", True)
        hdr_color = (0, 110, 55) if success else (140, 35, 35)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=hdr_color)
        d.text((6, 5), "SUCCESS" if success else "RESULT", font=self._font, fill=self.C_HDR_FG)

        lines = []
        for k, v in response.items():
            lines.extend(self._wrap(f"{k}: {v}", 32))

        y = self.HEADER_H + 6
        for line in lines:
            if y + 14 > self.H:
                break
            d.text((6, y), line, font=self._font_s, fill=self.C_MSG_FG)
            y += 15

        driver.blit(img)
        time.sleep(duration)

    def show_waiting(self, driver: ST7789Driver, dots: int = 0):
        """Show 'Processing...' screen with animated dots."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.text((6, 5), "AI Camera", font=self._font, fill=self.C_HDR_FG)
        dot_str = "." * (dots % 4)
        d.text((10, self.H // 2 - 20), f"Processing{dot_str}", font=self._font, fill=(200, 200, 80))
        d.text((6, self.H - 18), "hold B: back", font=self._font_s, fill=(80, 80, 80))
        driver.blit(img)

    def show_data_result(self, driver: ST7789Driver, data):
        """Show pipeline result data on screen."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=(0, 110, 55))
        d.text((6, 5), "Result", font=self._font, fill=self.C_HDR_FG)

        if isinstance(data, dict):
            lines = []
            for k, v in data.items():
                lines.extend(self._wrap(f"{k}: {v}", 32))
        elif isinstance(data, str):
            lines = self._wrap(data, 32)
        else:
            lines = self._wrap(str(data), 32)

        y = self.HEADER_H + 6
        for line in lines:
            if y + 14 > self.H - 20:
                break
            d.text((6, y), line, font=self._font_s, fill=self.C_MSG_FG)
            y += 15

        d.text((6, self.H - 18), "B:new photo  hold:back", font=self._font_s, fill=(80, 80, 80))
        driver.blit(img)

    def show_error_screen(self, driver: ST7789Driver, msg: str, duration: float = 3.0):
        """Show error screen for duration seconds."""
        self._show_error(driver, msg)
        time.sleep(duration)

    # ── Capture ───────────────────────────────────────────────────────────────

    def _capture(self) -> tuple[Image.Image, str]:
        if not self.is_available():
            raise CameraError(f"No camera at {self.device}")

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.photo_dir, f"photo_{ts}.jpg")

        log.info("capture: device=%s path=%s", self.device, path)
        result = subprocess.run(
            ["fswebcam", "-d", self.device,
             "-r", "3264x2448", "--no-banner", "--quiet",
             "--skip", "10",      # skip 10 frames so camera auto-exposes
             "--jpeg", "95",      # JPEG quality 0-100
             path],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.decode().strip() or "fswebcam failed"
            log.error("capture: fswebcam error: %s", err)
            raise CameraError(err)

        if not os.path.exists(path):
            log.error("capture: fswebcam returncode=0 but file missing: %s", path)
            raise CameraError("fswebcam ran but file was not created")

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

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _wrap(text: str, width: int) -> list[str]:
        """Simple word-wrap at character width."""
        words = text.split()
        lines, line = [], ""
        for w in words:
            if len(line) + len(w) + (1 if line else 0) <= width:
                line = f"{line} {w}" if line else w
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
        return lines or [""]


class CameraError(Exception):
    pass
