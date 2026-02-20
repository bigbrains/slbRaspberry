# SLB

Python project for Raspberry Pi Zero 2W with 1.54" TFT SPI display (ST7789, 240x240).

## Display Wiring

| Display Pin | Raspberry Pi Pin | GPIO     | Description       |
|-------------|-----------------|----------|-------------------|
| VCC         | Pin 1            | 3.3V     | Power             |
| GND         | Pin 6            | GND      | Ground            |
| SCL / SCK   | Pin 23           | GPIO11   | SPI Clock         |
| SDA / MOSI  | Pin 19           | GPIO10   | SPI MOSI          |
| CS1         | Pin 24           | GPIO8    | SPI Chip Select 0 |
| DC          | Pin 18           | GPIO24   | Data/Command      |
| RES         | Pin 22           | GPIO25   | Reset             |
| BLK         | Pin 1            | 3.3V     | Backlight (always on) |

## Setup

Enable SPI on the Raspberry Pi:
```bash
sudo raspi-config  # Interface Options → SPI → Enable
```

Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Print a line on the display:
```bash
python main.py "Hello World"
python main.py "Your text here"
```

## Project Structure

```
slb/
├── display/
│   ├── __init__.py
│   └── display_service.py   # DisplayService class
├── main.py                  # Entry point
├── requirements.txt
└── README.md
```
