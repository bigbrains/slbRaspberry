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

    C_BG      = (4,   4,   8)
    C_MSG_FG  = (200, 205, 215)
    C_ERR_FG  = (255,  80,  80)
    C_HDR_BG  = (18,  14,  38)
    C_HDR_FG  = (255, 255, 255)
    HEADER_H  = 26

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

    def submit_manual(self, api_base: str, photo_path: str) -> dict:
        """POST /api/manual with photos[] only (no scenarioId). Returns parsed JSON response."""
        url = f"{api_base}/api/manual"
        log.info("submit_manual: POST %s  file=%s", url, os.path.basename(photo_path))
        try:
            import requests
            with open(photo_path, "rb") as f:
                resp = requests.post(
                    url,
                    files={"photos[]": (os.path.basename(photo_path), f, "image/jpeg")},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                log.info("submit_manual: response %s", data)
                return data
        except Exception as e:
            log.error("submit_manual failed: %s", e)
            raise CameraError(f"submit_manual: {e}")

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

    def show_photo_fullscreen(self, driver: ST7789Driver, refs) -> None:
        """Display the current reference photo edge-to-edge with a page number badge."""
        photo = refs.current_img() if refs and refs.count > 0 else None
        if photo:
            img = photo.copy()
            d   = ImageDraw.Draw(img)
            label = refs.label          # e.g. "3/12"
            try:
                tw = int(self._font_s.getlength(label))
            except AttributeError:
                tw = self._font_s.getbbox(label)[2]
            pad = 4
            d.rectangle((0, 0, tw + pad * 2 + 1, 17), fill=(10, 10, 16))
            d.text((pad, 3), label, font=self._font_s, fill=(180, 180, 200))
            driver.blit(img)
        else:
            blank = Image.new("RGB", (self.W, self.H), self.C_BG)
            d = ImageDraw.Draw(blank)
            try:
                tw = int(self._font.getlength("no photos"))
            except AttributeError:
                tw = self._font.getbbox("no photos")[2]
            d.text(((self.W - tw) // 2, self.H // 2 - 8), "no photos",
                   font=self._font, fill=(50, 52, 65))
            driver.blit(blank)

    def show_camera_ready_refs(self, driver: ST7789Driver, title: str, refs) -> None:
        """Camera-ready screen with reference photo as background (if any).
        refs — ManualRefPhotos instance (or any object with .count, .current_img(), .label).
        """
        ref_img = refs.current_img() if refs and refs.count > 0 else None

        if ref_img:
            # Use reference photo as full background
            overlay = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
            d_ov    = ImageDraw.Draw(overlay)
            # Darken header and footer bars
            d_ov.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=(0, 0, 0, 210))
            d_ov.rectangle((0, self.H - 46, self.W - 1, self.H - 1), fill=(0, 0, 0, 215))
            img = Image.alpha_composite(ref_img.convert("RGBA"), overlay).convert("RGB")
        else:
            img = Image.new("RGB", (self.W, self.H), self.C_BG)

        d = ImageDraw.Draw(img)

        # Header (only draw bg rectangle when no ref photo)
        if not ref_img:
            d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=(45, 35, 75))
        d.text((8, 7), title, font=self._font, fill=self.C_HDR_FG)

        # "ready" pill
        pill_x = self.W - 46
        d.rectangle((pill_x, 8, self.W - 8, self.HEADER_H - 8), fill=(12, 36, 24))
        d.text((pill_x + 3, 9), "ready", font=self._font_s, fill=(60, 180, 100))

        # Counter badge (top-left, below header)
        if refs and refs.count > 0:
            label = refs.label
            d.text((8, self.HEADER_H + 4), label, font=self._font_s, fill=(200, 200, 200))

        # Footer hints
        hint_y = self.H - 40
        if not ref_img:
            d.line((8, hint_y, self.W - 8, hint_y), fill=(22, 22, 32))
        hint_y += 5
        d.text((8, hint_y),      "B    — capture & submit",  font=self._font_s, fill=(150, 155, 165))
        if refs and refs.count > 0:
            d.text((8, hint_y + 12), "A    — browse refs",   font=self._font_s, fill=(100, 105, 115))
            d.text((8, hint_y + 24), "hold B — back",        font=self._font_s, fill=(55, 58, 68))
        else:
            d.text((8, hint_y + 12), "hold B — back",        font=self._font_s, fill=(55, 58, 68))

        driver.blit(img)

    def show_camera_ready_split(self, driver: ST7789Driver, title: str, refs) -> None:
        """Split view: top half = API uploads, bottom half = cropped uploads."""
        W, H     = self.W, self.H
        HDR_H    = 22
        MID      = HDR_H + (H - HDR_H) // 2   # 131
        LABEL_H  = 15
        HINT_H   = 16

        img = Image.new("RGB", (W, H), self.C_BG)
        d   = ImageDraw.Draw(img)

        # Header
        d.rectangle((0, 0, W - 1, HDR_H - 1), fill=self.C_HDR_BG)
        d.line((0, HDR_H - 1, W - 1, HDR_H - 1), fill=(45, 35, 75))
        d.text((8, 6), title, font=self._font_s, fill=self.C_HDR_FG)
        d.rectangle((W - 44, 5, W - 6, HDR_H - 5), fill=(12, 36, 24))
        d.text((W - 41, 6), "ready", font=self._font_s, fill=(60, 180, 100))

        # Top section: API photos
        api_active = refs is not None and refs.current_source == "api"
        api_border = (55, 190, 100) if api_active else (30, 30, 46)
        api_photo  = refs.api_img() if refs else None
        api_y0, api_y1 = HDR_H, MID - 1
        api_th = api_y1 - api_y0 - LABEL_H

        if api_photo:
            y_off = max(0, (H - api_th) // 2)
            strip = api_photo.crop((0, y_off, W, min(H, y_off + api_th)))
            img.paste(strip, (0, api_y0))
        else:
            cx, cy = W // 2, api_y0 + (api_y1 - api_y0 - LABEL_H) // 2 - 6
            d.text((cx - 26, cy), "no photos", font=self._font_s, fill=(40, 42, 55))

        d.rectangle((0, api_y0, W - 1, api_y1), outline=api_border,
                    width=2 if api_active else 1)
        lbl_y = api_y1 - LABEL_H
        d.rectangle((0, lbl_y, W - 1, api_y1), fill=(6, 8, 14))
        api_lbl = refs.api_label if refs else "API —"
        d.text((6, lbl_y + 2), api_lbl, font=self._font_s,
               fill=(200, 220, 200) if api_active else (100, 110, 120))

        # Divider
        d.line((0, MID, W - 1, MID), fill=(40, 40, 60))

        # Bottom section: Cropped photos
        crop_active = refs is not None and refs.current_source == "cropped"
        crop_border = (55, 190, 100) if crop_active else (30, 30, 46)
        crop_photo  = refs.cropped_img() if refs else None
        crop_y0, crop_y1 = MID + 1, H - HINT_H - 1
        crop_th = crop_y1 - crop_y0 - LABEL_H

        if crop_photo:
            y_off = max(0, (H - crop_th) // 2)
            strip = crop_photo.crop((0, y_off, W, min(H, y_off + crop_th)))
            img.paste(strip, (0, crop_y0))
        else:
            cx, cy = W // 2, crop_y0 + (crop_y1 - crop_y0 - LABEL_H) // 2 - 6
            d.text((cx - 26, cy), "no photos", font=self._font_s, fill=(40, 42, 55))

        d.rectangle((0, crop_y0, W - 1, crop_y1), outline=crop_border,
                    width=2 if crop_active else 1)
        lbl2_y = crop_y1 - LABEL_H
        d.rectangle((0, lbl2_y, W - 1, crop_y1), fill=(6, 8, 14))
        crop_lbl = refs.cropped_label if refs else "CROP —"
        d.text((6, lbl2_y + 2), crop_lbl, font=self._font_s,
               fill=(200, 220, 200) if crop_active else (100, 110, 120))

        # Footer hints
        d.text((6, H - HINT_H + 2), "B: capture  A: browse  hold: back",
               font=self._font_s, fill=(80, 85, 100))

        driver.blit(img)

    def show_camera_ready(self, driver: ST7789Driver, scenario_name: str):
        """Show camera-ready screen with scenario name and button hints."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=(45, 35, 75))
        d.text((8, 7), "AI Camera", font=self._font, fill=self.C_HDR_FG)
        # "ready" pill
        d.rectangle((self.W - 46, 8, self.W - 8, self.HEADER_H - 8), fill=(12, 36, 24))
        d.text((self.W - 43, 9), "ready", font=self._font_s, fill=(60, 180, 100))

        y = self.HEADER_H + 12
        d.text((8, y), "SCENARIO", font=self._font_s, fill=(65, 65, 90))
        y += 14
        for line in self._wrap(scenario_name, 28):
            d.text((8, y), line, font=self._font, fill=(100, 185, 255))
            y += 17

        # camera preview placeholder box
        box_top = y + 8
        box_bot = self.H - 46
        if box_bot > box_top + 20:
            d.rectangle((8, box_top, self.W - 8, box_bot), fill=(10, 10, 16))
            d.rectangle((8, box_top, self.W - 8, box_bot), outline=(28, 28, 44))
            mid_x = self.W // 2
            mid_y = (box_top + box_bot) // 2
            d.text((mid_x - 8, mid_y - 6), "[ ]", font=self._font_s, fill=(38, 38, 55))

        hint_y = self.H - 40
        d.line((8, hint_y, self.W - 8, hint_y), fill=(22, 22, 32))
        hint_y += 6
        d.text((8, hint_y),      "B    — capture & submit", font=self._font_s, fill=(150, 155, 165))
        d.text((8, hint_y + 14), "LEFT — back to menu",     font=self._font_s, fill=(55, 58, 68))
        driver.blit(img)

    def show_response(self, driver: ST7789Driver, response: dict, duration: float = 5.0):
        """Display API response on screen for duration seconds, then return."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)

        success   = response.get("success", True)
        hdr_color = (6, 32, 18) if success else (38, 10, 10)
        accent    = (32, 150, 72) if success else (140, 35, 35)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=hdr_color)
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=accent)
        label = "SUCCESS" if success else "RESULT"
        d.text((8, 7), label, font=self._font, fill=self.C_HDR_FG)

        y = self.HEADER_H + 8
        for k, v in response.items():
            if y + 14 > self.H - 16:
                break
            d.text((8, y), str(k), font=self._font_s, fill=(75, 75, 95))
            y += 13
            for line in self._wrap(str(v), 32):
                if y + 13 > self.H - 16:
                    break
                d.text((8, y), line, font=self._font_s, fill=self.C_MSG_FG)
                y += 13
            y += 3
            d.line((8, y, self.W - 8, y), fill=(20, 26, 20))
            y += 5

        # footer hint
        d.rectangle((0, self.H - 16, self.W - 1, self.H - 1), fill=(6, 6, 10))
        d.text((8, self.H - 13), "auto-dismiss…", font=self._font_s, fill=(38, 42, 52))
        driver.blit(img)
        time.sleep(duration)

    def show_waiting(self, driver: ST7789Driver, dots: int = 0):
        """Show 'Processing...' screen with animated dots."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=self.C_HDR_BG)
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=(45, 35, 75))
        d.text((8, 7), "AI Camera", font=self._font, fill=self.C_HDR_FG)
        # "processing" pill
        d.rectangle((self.W - 78, 8, self.W - 8, self.HEADER_H - 8), fill=(28, 18, 48))
        d.text((self.W - 75, 9), "processing", font=self._font_s, fill=(150, 100, 220))

        dot_str = "." * (dots % 4)
        label = f"Analysing image{dot_str}"
        try:
            lw = int(self._font.getlength(label))
        except AttributeError:
            lw = self._font.getbbox(label)[2]
        d.text(((self.W - lw) // 2, self.H // 2 - 12), label,
               font=self._font, fill=(175, 140, 240))
        d.text((8, self.H - 16), "hold B: cancel", font=self._font_s, fill=(50, 50, 65))
        driver.blit(img)

    def show_data_result(self, driver: ST7789Driver, data):
        """Show pipeline result data on screen."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=(6, 28, 16))
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=(28, 120, 65))
        d.text((8, 7), "Result", font=self._font, fill=self.C_HDR_FG)

        LINE_H   = 13   # px per text line
        SEP_GAP  = 6    # px gap around separator line
        FOOTER_H = 20

        y = self.HEADER_H + 6

        if isinstance(data, dict):
            items = [(k, v) for k, v in data.items() if v != 0]
            for i, (k, v) in enumerate(items):
                # question key
                key_lines = self._wrap(str(k), 32)
                for line in key_lines:
                    if y + LINE_H > self.H - FOOTER_H:
                        break
                    d.text((6, y), line, font=self._font_s, fill=(150, 200, 255))
                    y += LINE_H

                # answer value — indented
                val_lines = self._wrap(str(v), 30)
                for line in val_lines:
                    if y + LINE_H > self.H - FOOTER_H:
                        break
                    d.text((12, y), line, font=self._font_s, fill=self.C_MSG_FG)
                    y += LINE_H

                # separator line between items (not after the last one)
                if i < len(items) - 1:
                    y += SEP_GAP
                    if y < self.H - FOOTER_H:
                        d.line((6, y, self.W - 6, y), fill=(120, 120, 120))
                    y += SEP_GAP + LINE_H  # 2 lines of space before next question
        elif isinstance(data, str):
            for line in self._wrap(data, 32):
                if y + LINE_H > self.H - FOOTER_H:
                    break
                d.text((6, y), line, font=self._font_s, fill=self.C_MSG_FG)
                y += LINE_H
        else:
            for line in self._wrap(str(data), 32):
                if y + LINE_H > self.H - FOOTER_H:
                    break
                d.text((6, y), line, font=self._font_s, fill=self.C_MSG_FG)
                y += LINE_H

        d.text((6, self.H - 18), "B:new photo  hold:back", font=self._font_s, fill=(80, 80, 80))
        driver.blit(img)

    def show_no_network(self, driver: ST7789Driver):
        """Show persistent 'no network' screen with button hints."""
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=(38, 14, 4))
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=(140, 55, 10))
        d.text((8, 7), "AI Camera", font=self._font, fill=(255, 140, 60))
        # "offline" pill
        d.rectangle((self.W - 52, 8, self.W - 8, self.HEADER_H - 8), fill=(50, 14, 8))
        d.text((self.W - 49, 9), "offline", font=self._font_s, fill=(220, 70, 50))

        # centered content
        cy = self.HEADER_H + 30
        # icon area
        icon_label = "no signal"
        try:
            iw = int(self._font.getlength(icon_label))
        except AttributeError:
            iw = self._font.getbbox(icon_label)[2]
        d.text(((self.W - iw) // 2, cy), icon_label, font=self._font, fill=(180, 80, 30))
        cy += 24
        d.text((self.W // 2 - 50, cy), "Connect to WiFi", font=self._font_s, fill=(120, 120, 130))
        cy += 14
        d.text((self.W // 2 - 30, cy), "and retry.", font=self._font_s, fill=(90, 90, 100))

        hint_y = self.H - 52
        d.line((8, hint_y, self.W - 8, hint_y), fill=(28, 22, 18))
        hint_y += 7
        d.text((8, hint_y),      "A      — retry",        font=self._font_s, fill=(80, 175, 90))
        d.text((8, hint_y + 14), "B      — back to menu", font=self._font_s, fill=(95, 95, 105))
        d.text((8, hint_y + 28), "hold B — restart app",  font=self._font_s, fill=(175, 130, 45))
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

        # Enable continuous autofocus if the camera supports it, then let it settle
        af = subprocess.run(
            ["v4l2-ctl", "-d", self.device, "--set-ctrl=focus_automatic_continuous=1"],
            capture_output=True,
        )
        if af.returncode != 0:
            # Older V4L2 control name
            subprocess.run(
                ["v4l2-ctl", "-d", self.device, "--set-ctrl=focus_auto=1"],
                capture_output=True,
            )
        time.sleep(1.5)   # wait for autofocus to settle

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
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=(45, 35, 75))
        d.text((8, 7), "AI Camera", font=self._font, fill=self.C_HDR_FG)
        try:
            tw = int(self._font.getlength(text))
        except AttributeError:
            tw = self._font.getbbox(text)[2]
        d.text(((self.W - tw) // 2, self.H // 2 - 8), text, font=self._font, fill=self.C_MSG_FG)
        driver.blit(img)

    def _show_error(self, driver: ST7789Driver, msg: str):
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HEADER_H - 1), fill=(38, 10, 10))
        d.line((0, self.HEADER_H - 1, self.W - 1, self.HEADER_H - 1), fill=(140, 35, 35))
        d.text((8, 7), "AI Camera", font=self._font, fill=self.C_HDR_FG)
        d.text((8, self.HEADER_H + 10), "Camera error:", font=self._font,   fill=self.C_ERR_FG)
        d.text((8, self.HEADER_H + 28), msg,             font=self._font_s, fill=self.C_MSG_FG)
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
