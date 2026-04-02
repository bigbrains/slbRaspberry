"""
display/wifi_menu.py — WiFi network switching with 30-second auto-rollback,
and an IP / connectivity info screen.

NetworkMode controls:
  UP / DOWN — navigate network list
  B         — switch to selected network (then press B again within 30s to confirm,
               or the Pi reverts to the previous network automatically)
  LEFT      — back to menu (cancels any pending rollback)

IPInfoMode controls:
  A / B     — run connectivity test (fetches google.com)
  LEFT      — back to menu
"""
import socket
import subprocess
import threading
import time
import logging
import urllib.request

import RPi.GPIO as GPIO
from PIL import Image, ImageDraw

from display.menu import _load_font, ST7789Driver

log = logging.getLogger(__name__)

# ── Known networks ────────────────────────────────────────────────────────────
NETWORKS = {
    "TP-Link_9860":       "TP-Link_9860",
    "iPhone (Vladyslav)": "iPhone (Vladyslav)",
}
IPHONE_PSK       = "00000000"
ROLLBACK_SECONDS = 30

# ── Button pins ───────────────────────────────────────────────────────────────
_PIN_UP   = 17
_PIN_DOWN = 6
_PIN_LEFT = 22
_PIN_A    = 26   # GPIO26, Pin 37
_PIN_B    = 19   # GPIO19, Pin 35
_ALL_PINS = (_PIN_UP, _PIN_DOWN, _PIN_LEFT, _PIN_A, _PIN_B)
_DEBOUNCE   = 0.2
_LONG_PRESS = 0.7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_release(pin):
    while GPIO.input(pin) == GPIO.LOW:
        time.sleep(0.01)
    time.sleep(0.05)


def _current_connection() -> str:
    """Return the nmcli connection name currently active on wlan0."""
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "con", "show", "--active"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            name, _, dev = line.partition(":")
            if dev.strip() == "wlan0":
                return name.strip()
    except Exception:
        pass
    return ""


def _switch_network(name: str) -> bool:
    """Activate a NetworkManager connection by name. Returns True on success."""
    try:
        r = subprocess.run(
            ["nmcli", "con", "up", name],
            capture_output=True, text=True, timeout=25,
        )
        return r.returncode == 0
    except Exception:
        return False


def _ensure_iphone_psk():
    """Ensure the iPhone profile has the correct PSK (idempotent)."""
    try:
        subprocess.run(
            ["nmcli", "con", "modify", "iPhone (Vladyslav)",
             "wifi-sec.key-mgmt", "wpa-psk",
             "wifi-sec.psk", IPHONE_PSK],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


# ── NetworkMode ───────────────────────────────────────────────────────────────

class NetworkMode:
    """
    WiFi network selector with 30-second auto-rollback.

    UP / DOWN — navigate list
    B         — connect; then press B again within 30 s to confirm, else auto-revert
    LEFT      — back to menu
    """

    W, H        = 240, 240
    HDR_H       = 28
    ITEM_H      = 28
    C_HDR       = (8,  28,  16)
    C_HDR_ACC   = (28, 120,  60)
    C_BG        = (4,   6,   8)
    C_FG        = (145, 155, 145)
    C_SEL_BG    = (8,  28,  18)
    C_SEL_ACC   = (34, 197,  94)
    C_FG_S      = (255, 255, 255)
    C_OK        = (60,  195,  80)
    C_WARN      = (215,  95,  50)
    C_INFO      = (180, 195,  70)
    C_HINT      = (52,  58,  52)

    def __init__(self):
        self._font   = _load_font(13)
        self._font_s = _load_font(11)
        self._labels = list(NETWORKS.keys())
        self._sel    = 0
        self._rb_name   = ""
        self._rb_thread: threading.Thread | None = None
        self._rb_cancel = threading.Event()
        self._rb_end    = 0.0
        self._status    = ""
        self._status_ok = True
        _ensure_iphone_psk()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self, driver: ST7789Driver):
        _wait_release(_PIN_B)
        self._status = ""
        self._render(driver)

        prev      = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t    = {p: 0.0       for p in _ALL_PINS}
        b_down_at = 0.0

        while True:
            now = time.monotonic()
            for pin in (_PIN_A, _PIN_B):
                state = GPIO.input(pin)
                if pin == _PIN_B:
                    if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                        b_down_at = now
                    elif prev[pin] == GPIO.LOW and state == GPIO.HIGH:
                        held = now - b_down_at
                        if held >= _LONG_PRESS:
                            self._cancel_rollback()
                            prev[pin] = state
                            return
                        else:
                            self._do_switch(driver)
                elif pin == _PIN_A:
                    if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                        if now - last_t[pin] >= _DEBOUNCE:
                            last_t[pin] = now
                            self._sel = (self._sel + 1) % len(self._labels)
                            self._status = ""
                            self._render(driver)
                prev[pin] = state

            if self._rb_thread and self._rb_thread.is_alive():
                self._render(driver)
            time.sleep(0.2)

    # ── Switch + rollback ─────────────────────────────────────────────────────

    def _do_switch(self, driver: ST7789Driver):
        target    = self._labels[self._sel]
        conn_name = NETWORKS[target]
        current   = _current_connection()

        if current == conn_name:
            self._status    = "Already connected"
            self._status_ok = True
            self._render(driver)
            return

        self._rb_name   = current
        self._status    = "Connecting..."
        self._status_ok = True
        self._render(driver)
        log.info("Switching %s → %s", current, conn_name)

        ok = _switch_network(conn_name)
        if not ok:
            log.error("Switch to %s failed", conn_name)
            self._status    = "Connection failed"
            self._status_ok = False
            self._render(driver)
            return

        # Start rollback timer
        self._rb_cancel.clear()
        self._rb_end    = time.monotonic() + ROLLBACK_SECONDS
        self._rb_thread = threading.Thread(target=self._rollback_worker, daemon=True)
        self._rb_thread.start()

        self._status    = "Connected! B=confirm"
        self._status_ok = True
        self._render(driver)

        # Wait for B-confirm or rollback timeout
        prev_b = GPIO.HIGH
        last_b = time.monotonic()
        while self._rb_thread.is_alive():
            state = GPIO.input(_PIN_B)
            if prev_b == GPIO.HIGH and state == GPIO.LOW:
                if time.monotonic() - last_b >= _DEBOUNCE:
                    self._cancel_rollback()
                    self._status    = f"Confirmed: {target}"
                    self._status_ok = True
                    self._render(driver)
                    time.sleep(1.2)
                    return
            prev_b = state
            self._render(driver)
            time.sleep(0.2)

        # Rollback fired
        self._status    = f"Reverted to {self._rb_name or 'prev'}"
        self._status_ok = False
        self._render(driver)
        time.sleep(2)

    def _rollback_worker(self):
        while time.monotonic() < self._rb_end:
            if self._rb_cancel.is_set():
                return
            time.sleep(0.1)
        if not self._rb_cancel.is_set() and self._rb_name:
            log.warning("Auto-rollback → %s", self._rb_name)
            _switch_network(self._rb_name)

    def _cancel_rollback(self):
        self._rb_cancel.set()
        if self._rb_thread:
            self._rb_thread.join(timeout=1)
        self._rb_thread = None

    # ── Render ────────────────────────────────────────────────────────────────

    def _render(self, driver: ST7789Driver):
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)

        # Header
        d.rectangle((0, 0, self.W - 1, self.HDR_H - 1), fill=self.C_HDR)
        d.line((0, self.HDR_H - 1, self.W - 1, self.HDR_H - 1), fill=self.C_HDR_ACC)
        d.text((8, 8), "Network", font=self._font, fill=self.C_FG_S)

        # Active connection — inline in header, right side
        current = _current_connection() or "none"
        conn_short = current if len(current) <= 14 else current[:13] + "…"
        try:
            cw = int(self._font_s.getlength(conn_short))
        except AttributeError:
            cw = self._font_s.getbbox(conn_short)[2]
        d.text((self.W - cw - 8, 10), conn_short, font=self._font_s, fill=self.C_INFO)

        # Network list
        list_top = self.HDR_H + 4
        for i, label in enumerate(self._labels):
            y      = list_top + i * self.ITEM_H
            is_sel = i == self._sel
            is_active = NETWORKS[label] == current
            if is_sel:
                d.rectangle((0, y, self.W - 1, y + self.ITEM_H - 2), fill=self.C_SEL_BG)
                d.rectangle((0, y, 2, y + self.ITEM_H - 2), fill=self.C_SEL_ACC)
            # signal indicator (decorative, right-aligned)
            sig = "▂▄▆█" if is_active else "▂▄▆░"
            sig_color = self.C_OK if is_active else (45, 55, 45)
            try:
                sw = int(self._font_s.getlength(sig))
            except AttributeError:
                sw = self._font_s.getbbox(sig)[2]
            d.text((self.W - sw - 8, y + 8), sig, font=self._font_s, fill=sig_color)
            d.text((8, y + 8), label,
                   font=self._font_s,
                   fill=self.C_FG_S if is_sel else self.C_FG)
            if not is_sel:
                d.line((6, y + self.ITEM_H - 2, self.W - 6, y + self.ITEM_H - 2),
                       fill=(16, 24, 16))

        # Rollback countdown
        if self._rb_thread and self._rb_thread.is_alive():
            remaining = max(0.0, self._rb_end - time.monotonic())
            bar_y = self.H - 50
            d.rectangle((0, bar_y, self.W - 1, self.H - 22), fill=(32, 14, 4))
            d.rectangle((0, bar_y, self.W - 1, bar_y), fill=(90, 38, 8))
            d.text((8, bar_y + 4),
                   f"Rollback in {remaining:.0f}s — B to keep",
                   font=self._font_s, fill=self.C_WARN)
            bx, by, bw, bh = 8, bar_y + 20, self.W - 16, 4
            d.rectangle((bx, by, bx + bw, by + bh), fill=(48, 24, 8))
            filled = int(bw * remaining / ROLLBACK_SECONDS)
            if filled > 0:
                d.rectangle((bx, by, bx + filled, by + bh), fill=self.C_WARN)

        # Status bar / hints
        status_y = self.H - 18
        d.rectangle((0, status_y, self.W - 1, self.H - 1), fill=(4, 6, 4))
        d.line((0, status_y, self.W - 1, status_y), fill=(14, 22, 14))
        if self._status:
            color = self.C_OK if self._status_ok else self.C_WARN
            d.text((8, status_y + 3), self._status, font=self._font_s, fill=color)
        else:
            d.text((8, status_y + 3), "B connect  ← back",
                   font=self._font_s, fill=self.C_HINT)

        driver.blit(img)


# ── IPInfoMode ────────────────────────────────────────────────────────────────

class IPInfoMode:
    """
    Shows local IP, external IP, and tests connectivity to google.com.

    A / B   — rerun test
    LEFT    — back to menu
    """

    W, H     = 240, 240
    HDR_H    = 28
    C_HDR    = (10,  14,  32)
    C_HDR_AC = (38,  60, 120)
    C_BG     = (4,   6,  10)
    C_FG     = (200, 205, 215)
    C_KEY    = (55,  65,  90)
    C_OK     = (65,  195,  80)
    C_FAIL   = (215,  90,  55)
    C_INFO   = (165, 175, 200)
    C_HINT   = (45,  50,  68)

    def __init__(self):
        self._font   = _load_font(13)
        self._font_s = _load_font(11)
        self._lines: list[tuple[str, tuple]] = []

    def run(self, driver: ST7789Driver):
        _wait_release(_PIN_B)
        self._run_test(driver)

        prev      = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t    = {p: 0.0       for p in _ALL_PINS}
        b_down_at = 0.0

        while True:
            now = time.monotonic()
            for pin in (_PIN_A, _PIN_B):
                state = GPIO.input(pin)
                if pin == _PIN_B:
                    if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                        b_down_at = now
                    elif prev[pin] == GPIO.LOW and state == GPIO.HIGH:
                        held = now - b_down_at
                        if held >= _LONG_PRESS:
                            prev[pin] = state
                            return
                        else:
                            self._run_test(driver)
                elif pin == _PIN_A:
                    if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                        if now - last_t[pin] >= _DEBOUNCE:
                            last_t[pin] = now
                            self._run_test(driver)
                prev[pin] = state
            time.sleep(0.05)

    # ── Test ─────────────────────────────────────────────────────────────────

    def _run_test(self, driver: ST7789Driver):
        log.info("IPInfoMode: running connectivity test")
        self._lines = []
        self._show(driver, "Testing...")

        local_ip = self._local_ip()
        self._lines.append((f"Local:  {local_ip}", self.C_INFO))
        self._show(driver)

        conn = _current_connection() or "none"
        self._lines.append((f"WiFi:   {conn}", self.C_INFO))
        self._show(driver)

        ext, ok = self._fetch("http://ifconfig.me/ip", max_bytes=64)
        if ok:
            log.info("IPInfoMode: ext IP = %s", ext.strip())
            self._lines.append((f"Ext IP: {ext.strip()}", self.C_OK))
        else:
            log.warning("IPInfoMode: ext IP unreachable: %s", ext)
            self._lines.append(("Ext IP: unreachable", self.C_FAIL))
        self._show(driver)

        body, ok = self._fetch("http://www.google.com", max_bytes=48)
        if ok:
            log.info("IPInfoMode: google reachable")
            self._lines.append(("Google: OK", self.C_OK))
            snippet = body[:28].replace("\n", " ").strip()
            if snippet:
                self._lines.append((f"  {snippet}", self.C_HINT))
        else:
            log.warning("IPInfoMode: google unreachable: %s", body)
            self._lines.append(("Google: FAIL", self.C_FAIL))

        self._lines.append(("", self.C_HINT))
        self._lines.append(("A/B:retest  ←:back", self.C_HINT))
        self._show(driver)

    @staticmethod
    def _local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "unknown"

    @staticmethod
    def _fetch(url: str, timeout: int = 8, max_bytes: int = 256) -> tuple[str, bool]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.81.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(max_bytes).decode("utf-8", errors="replace"), True
        except Exception as e:
            return str(e)[:30], False

    # ── Render ────────────────────────────────────────────────────────────────

    def _show(self, driver: ST7789Driver, status: str = ""):
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HDR_H - 1), fill=self.C_HDR)
        d.line((0, self.HDR_H - 1, self.W - 1, self.HDR_H - 1), fill=self.C_HDR_AC)
        d.text((8, 8), "IP / Network", font=self._font_s, fill=(200, 210, 240))

        if status:
            try:
                sw = int(self._font.getlength(status))
            except AttributeError:
                sw = self._font.getbbox(status)[2]
            d.text(((self.W - sw) // 2, self.H // 2 - 8),
                   status, font=self._font, fill=self.C_INFO)
        else:
            y = self.HDR_H + 8
            for text, color in self._lines:
                # Split "Key: value" into key/value for two-column style
                if ": " in text and not text.startswith(" ") and not text.startswith("A/B"):
                    key, _, val = text.partition(": ")
                    key = key.strip()
                    val = val.strip()
                    try:
                        kw = int(self._font_s.getlength(key + ":"))
                    except AttributeError:
                        kw = self._font_s.getbbox(key + ":")[2]
                    d.text((8, y), key + ":", font=self._font_s, fill=self.C_KEY)
                    d.text((56, y), val, font=self._font_s, fill=color)
                else:
                    d.text((8, y), text, font=self._font_s, fill=color)
                y += 18

        driver.blit(img)
