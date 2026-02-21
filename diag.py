import spidev, RPi.GPIO as GPIO, time
from PIL import Image

DC, RST = 24, 25
GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
GPIO.setup(DC, GPIO.OUT); GPIO.setup(RST, GPIO.OUT)
spi = spidev.SpiDev(); spi.open(0,0); spi.max_speed_hz=4000000; spi.mode=0

def cmd(c): GPIO.output(DC,0); spi.writebytes([c])
def data(b):
    GPIO.output(DC,1)
    for i in range(0, len(b), 1024):
        spi.writebytes(list(b[i:i+1024]))

GPIO.output(RST,0); time.sleep(0.05)
GPIO.output(RST,1); time.sleep(0.12)
cmd(0x01); time.sleep(0.15)
cmd(0x11); time.sleep(0.15)
cmd(0x3A); data(b'\x55')
cmd(0x36); data(b'\x60')
cmd(0x21); cmd(0x29); time.sleep(0.1)

# Step 1: raw red fill (same as hello_fast approach)
print('Step 1: raw red fill — screen should go RED')
cmd(0x2A); data(bytes([0,0,0,239]))
cmd(0x2B); data(bytes([0,0,0,239]))
cmd(0x2C)
GPIO.output(DC,1)
chunk = bytes([0xF8,0x00])*512
for _ in range(240*240//512): spi.writebytes(list(chunk))
time.sleep(3)

# Step 2: PIL -> RGB565 -> display
print('Step 2: PIL green via blit — screen should go GREEN')
img = Image.new('RGB', (240,240), (0,200,0))
buf = bytearray(240*240*2)
idx = 0
for r,g,b in img.getdata():
    c = ((r&0xF8)<<8)|((g&0xFC)<<3)|(b>>3)
    buf[idx]=(c>>8)&0xFF; buf[idx+1]=c&0xFF; idx+=2
print(f'  first 4 bytes: {list(buf[:4])}  (expect ~[0x02, 0x18, ...])')
cmd(0x2A); data(bytes([0,0,0,239]))
cmd(0x2B); data(bytes([0,0,0,239]))
cmd(0x2C)
data(bytes(buf))
print('Step 2 done')
time.sleep(3)

spi.close(); GPIO.cleanup()
print('All done')
