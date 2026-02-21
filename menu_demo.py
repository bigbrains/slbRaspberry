"""
menu_demo.py  –  run with:  sudo python3 menu_demo.py

Controls (keyboard over SSH):
  w / k / ↑   move up
  s / j / ↓   move down
  Enter        confirm selection
  q / Ctrl-C   quit
"""
import sys
import tty
import termios
from display.menu import ST7789Driver, Menu


# ── Placeholder action classes ────────────────────────────────────────────────

class WiFiSettings:       pass
class BluetoothSettings:  pass
class DisplayBrightness:  pass
class VolumeControl:      pass
class NetworkInfo:        pass
class SystemUpdate:       pass
class TimeDate:           pass
class Language:           pass
class Timezone:           pass
class SshServer:          pass
class FileManager:        pass
class ProcessViewer:      pass
class CpuTemperature:     pass
class RamUsage:           pass
class StorageInfo:        pass
class AudioOutput:        pass
class FirmwareUpdate:     pass
class FactoryReset:       pass
class Reboot:             pass
class Shutdown:           pass


MENU_ITEMS: dict[str, type] = {
    "WiFi Settings":      WiFiSettings,
    "Bluetooth":          BluetoothSettings,
    "Display Brightness": DisplayBrightness,
    "Volume Control":     VolumeControl,
    "Network Info":       NetworkInfo,
    "System Update":      SystemUpdate,
    "Time & Date":        TimeDate,
    "Language":           Language,
    "Timezone":           Timezone,
    "SSH Server":         SshServer,
    "File Manager":       FileManager,
    "Process Viewer":     ProcessViewer,
    "CPU Temperature":    CpuTemperature,
    "RAM Usage":          RamUsage,
    "Storage Info":       StorageInfo,
    "Audio Output":       AudioOutput,
    "Firmware Update":    FirmwareUpdate,
    "Factory Reset":      FactoryReset,
    "Reboot":             Reboot,
    "Shutdown":           Shutdown,
}


# ── Input helper ─────────────────────────────────────────────────────────────

def getch() -> str:
    """Read one keypress without waiting for Enter (works over SSH with PTY)."""
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        # No real TTY (piped/non-interactive) — fall back to line input
        line = sys.stdin.readline().strip()
        return line[0] if line else ' '
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':           # escape sequence → read remainder
            ch += sys.stdin.read(2)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    driver = ST7789Driver()
    menu   = Menu(MENU_ITEMS, title="SETTINGS")
    menu.render(driver)

    print("w/↑  up    s/↓  down    Enter  select    q  quit")

    try:
        while True:
            key = getch()

            if key in ('w', 'k', '\x1b[A'):      # up
                menu.up()
                menu.render(driver)

            elif key in ('s', 'j', '\x1b[B'):     # down
                menu.down()
                menu.render(driver)

            elif key in ('\r', '\n'):              # Enter — act on selection
                label, cls = menu.select()
                print(f"\nSelected: {label}  →  {cls.__name__}")
                # TODO: cls().run(driver) or similar

            elif key in ('q', '\x03', '\x04'):    # q / Ctrl-C / Ctrl-D
                break

    finally:
        driver.close()


if __name__ == "__main__":
    main()
