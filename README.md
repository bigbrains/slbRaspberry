# SLB

Python project for Raspberry Pi Zero 2W with 1.54" TFT SPI display (ST7789, 240×240).

## Display Wiring

| Display Pin | Raspberry Pi Pin | GPIO   | Description           |
|-------------|-----------------|--------|-----------------------|
| VCC         | Pin 1            | 3.3V   | Power                 |
| GND         | Pin 6            | GND    | Ground                |
| SCL / SCK   | Pin 23           | GPIO11 | SPI Clock             |
| SDA / MOSI  | Pin 19           | GPIO10 | SPI MOSI              |
| CS1         | Pin 24           | GPIO8  | SPI Chip Select 0     |
| DC          | Pin 18           | GPIO24 | Data/Command          |
| RES         | Pin 22           | GPIO25 | Reset                 |
| BLK         | Pin 17           | 3.3V   | Backlight (always on) |

## Button Wiring

Each button is wired between its GPIO pin and GND. Internal pull-ups are used — no external resistors needed.

| Button      | Pi Pin | GPIO   | GND Pin |
|-------------|--------|--------|---------|
| D-pad UP    | Pin 11 | GPIO17 | Pin 14  |
| D-pad DOWN  | Pin 31 | GPIO6  | Pin 30  |
| D-pad LEFT  | Pin 15 | GPIO22 | Pin 14  |
| D-pad RIGHT | Pin 16 | GPIO23 | Pin 14  |
| Button A    | Pin 29 | GPIO5  | Pin 30  |
| Button B    | Pin 13 | GPIO27 | Pin 14  |

## Button Controls

| Button   | Menu             | Inside a mode         |
|----------|------------------|-----------------------|
| A        | next item        | next / confirm        |
| UP       | previous item    | previous              |
| DOWN     | next item        | next                  |
| B short  | select / enter   | action / confirm      |
| B long   | —                | back to previous menu |

## Setup

Enable SPI on the Raspberry Pi:
```bash
sudo raspi-config  # Interface Options → SPI → Enable
```

Install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
# Main menu (runs on boot via systemd)
sudo systemctl start menu_show

# Manual run
sudo .venv/bin/python menu_buttons.py
```

### Systemd service

```bash
sudo systemctl start menu_show     # start
sudo systemctl stop menu_show      # stop
sudo systemctl restart menu_show   # restart after code changes
sudo systemctl status menu_show    # status + recent logs
sudo journalctl -u menu_show -f    # live logs
```

## Sync to Pi

```bash
rsync -av --exclude='.venv' --exclude='.git' --exclude='.idea' \
  /Users/oksanka/slbRaspberry/ pi@raspberrypi.local:~/slb/
ssh pi@raspberrypi.local "sudo systemctl restart menu_show"
```

## Menu Modes

| Mode        | Description                                          |
|-------------|------------------------------------------------------|
| Questions   | Paged Q&A, A/B = next page, B long = back            |
| AI Camera   | Select scenario → capture photo → POST /api/solve    |
| Button Test | Visual button tester, B long = back                  |
| Network     | WiFi network management                              |
| IP Info     | Show current IP address                              |

## Project Structure

```
slb/
├── display/
│   ├── menu.py              # ST7789Driver + Menu class
│   ├── simple_questions.py  # SimpleQuestions class
│   ├── ai_camera.py         # AICamera class + API integration
│   └── wifi_menu.py         # NetworkMode, IPInfoMode
├── menu_buttons.py          # main entry point (button navigation)
├── menu_demo.py             # mode classes + MENU_ITEMS
├── buttons_demo.py          # standalone button tester
├── menu_show.service        # systemd unit
└── README.md
```
