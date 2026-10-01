# Panel MCU link (`/dev/subucom_spi0.1`)

`subucom_spi.h`, ioctl type `'p'`:

| ioctl | use |
|---|---|
| `SUBUCOM_IOC_MESSAGE(1)` = `0x40107000` | set the frame to transmit: `struct subucom_ioc_transfer { u8 multi_id, _reserved, part_id, part_num; u32 bytes; u64 tx_buf; }` |
| `RD/WR_TIMER_STATUS` (`'p'`,1, u8) | 1 starts the periodic exchange |
| `RD/WR_TIMER_INTERVAL` (2, u32) | ms between exchanges (app: 2 ms panel, 3 ms codec) |
| `RD/WR_BITS_PER_WORD` (3, u16), `RD/WR_RX_BYTES` (4, u32) | word size and reply length (panel 128, codec 4) |
| `WR_UPDATE_DUMMY` (5), `RD_GPIO_LEVEL` (6), `WR_GPIO_NUM` (7), `RD/WR_ENDIAN` (8/9) | |

The driver exchanges the current tx frame every interval. After each exchange
it keeps the reply, sets `rx_detected` (poll → `POLLIN`), and `read()` returns
the latest reply. With 32-bit words and big endian the driver byte-swaps each
32-bit word on `read()`.

Frames are 128 bytes. Bytes `0x7C-0x7D` = CRC-16/X-25 (reflected, init
`0xFFFF`, xorout `0xFFFF`) over bytes 0..`0x7B`, little-endian. Same routine
for both directions (the app's own, which it also uses to check replies).

- App → panel: identifier `0x02`, then 32 colour lamps of 3 bytes (R, G, B)
  from byte 1: the 16 pads, then the 16 step keys (a step switched on from
  HOME lights lamp 16 + its number, `4a 02 00`). Then the two-level lamps,
  2 bits each, in bytes `0x61`–`0x6B` (table in `app/layout.py`). `0x6C` bit 1 asks for standby.
- Panel → app: identifier `0x01` (checked by the app's
  handler of the panel's data), then the input state:

| offset | contents |
|---|---|
| `0x01`–`0x06` | 46 buttons, one bit each |
| `0x01` bit 1 | main encoder push |
| `0x06` bit 0 | a switch |
| `0x08`,`0x0A`,`0x0C`,`0x0E`,`0x10`,`0x12` | encoders 1–6 (the knobs under the screen), 16-bit counters. The app takes differences |
| `0x14` | encoder 0, the rotary selector |
| `0x16`–`0x35`, `0x36`–`0x55` | pads 0–15, two 16-bit values each: how hard (0–1023), and a second reading that is above 59 while the pad is held |
| `0x56`, `0x58` | tempo slider: the centre's reference and the position. The app takes their difference, 0 at the − end to 1023 at the + end against a reference of 512 gives −16 % to +16 % on the ±16 range (nothing moves while TEMPO RESET's lamp is lit) |
| `0x5A` | FX LEVEL/DEPTH, 0–1023 (pot 1) |
| `0x5C` | the headphones' level (the knob on the unit's front), 0–1023, linearised through a table of the app's: at 0 the headphone output is silent, at 1023 a pad is as loud there as on the master |
| `0x5E`, `0x60` | the screen's touch panel, raw x and y (valid x 87–940, y 72–866, steady for 4 frames, and mapped to 764 x 449 at 18, 7 with `TouchPanelCalibration.xml`). The emulator sends touches as X mouse events instead |

Button bit → id (from the app's button handler): byte 1: bit0=1, bit2=5, bit3=6,
bit4=0x10, bit5=0x11, bit6=0x12, bit7=0x13. Byte 2: bit0=8, bit1=0xb,
bit2=0xc, bit3=0xd, bit4=0xa, bit5=9, bit6=0xe, bit7=0xf. Byte 3: bits 0–7 =
0x1a–0x21. Byte 4: bits 0–7 = 0x22–0x29. Byte 5: bits 0–3 = 0x2a–0x2d,
bit4=0, bit5=2, bit6=3, bit7=4. Byte 6: bit1=0x18, bit2=0x19, bit3=0x17,
bit4=0x16, bit5=0x14, bit6=0x15, bit7=7.

Identified by pressing them and watching the screen, the lamps and the
sound. A lamp's id is not its button's:

| button | frame bit | id | lamp |
|---|---|---|---|
| USB STOP (held: `do_umount`, the USB lamp goes dim) | byte 1 bit 0 | 1 | 0x00 (USB) |
| BACK (one level up) | byte 1 bit 2 | 5 | |
| HOME | byte 1 bit 3 | 6 | |
| MUTE, HOT SLICE, SLICE, SCALE | byte 1 bits 4–7 | 0x10–0x13 | 0x17–0x1a |
| SHIFT (with PATTERN: LENGTH, the step keys all light) | byte 2 bit 0 | 8 | |
| REC | byte 2 bit 1 | 0xb | 0x14 |
| STOP/GATE | byte 2 bit 2 | 0xc | 0x15 |
| PLAY/PAUSE | byte 2 bit 3 | 0xd | 0x16 |
| HOLD | byte 2 bit 4 | 0xa | 0x0b |
| MODE (steps through PITCH, REPEAT, USER1, USER2) | byte 2 bit 5 | 9 | 0x07–0x0a |
| SCENE, PATTERN | byte 2 bits 6, 7 | 0xe, 0xf | 0x47, 0x48 |
| the four bar keys | byte 5 bits 0–3 | 0x2a–0x2d | 0x3f–0x42?, with 0x43–0x46 the lamp over each |
| NUDGE +, NUDGE − | byte 6 bits 1, 2 | 0x18, 0x19 | |
| TEMPO RESET | byte 6 bit 3 | 0x17 | 0x1d |
| FX ON/OFF (a toggle, heard only with LEVEL/DEPTH above zero) | byte 6 bit 7 | 7 | 0x06: blinks while off, steady while on |
| step keys 1–8, 9–16 | byte 3 bits 0–7, byte 4 bits 0–7 | 0x1a–0x29 | colour lamps 16–31 |
| power/standby key: press and release puts the app in standby. From then on it asks the panel for it (tx `0x6C` bit 1, `transition Standby!`), see [power-standby.md](power-standby.md) | byte 5 bit 4 | 0 | |
| PROJECT (opens and closes its menu) | byte 5 bit 5 | 2 | 0x01 |
| LIVE SAMPLING | byte 5 bit 6 | 3 | 0x02 |
| FX | byte 5 bit 7 | 4 | 0x03 |
| TEMPO RANGE | byte 6 bit 4 | 0x16 | |
| SYNC / MASTER ("No LINKED Players found" with no deck on the Pro DJ Link network) | byte 6 bits 5, 6 | 0x14, 0x15 | 0x1B, 0x1C (byte 0x6A bits 0-1 and 2-3, where 3 is off and 1 is lit) |

A two-level lamp's two bits are 0 off, 3 dim, 1 bright (the app's table of them). 0x0c–0x13 are the strip's eight. Not matched to a control:
0x04, 0x05 (bright), 0x1b, 0x1c, 0x1e (bright).

## The touch strip (`/dev/cdc_spi2.0`)

The strip ("ribbon" in the app: `UIRibbon`, `RibbonController`) is not in
the panel's frame. It is what the second link carries: the same driver with
4-byte replies every 3 ms, read by the app's `CdcManager`, which makes
one 16-bit value of them, `(0x7F - byte 0) | byte 1 << 8`: bit 15 is set
while the strip is touched and the low 7 bits are the position, 0 at the
bottom to 127 at the top. The UI thread hands it to the ribbon
(`UIInputManager`'s map at +0xa0). The app lights the eight lamps beside the
strip itself, 0x0c (bottom) to 0x13 (top). In PITCH mode a touch at the
centre lights the middle two and the ends light four each.

The strip acts on a pad hit while it is touched: in PITCH mode the top and
the bottom shift the sound by the PITCH RANGE setting (2 semitones by
default, measured on a kick), in REPEAT mode a held pad repeats, faster the
higher the touch.

Byte 6 bit 0 of the panel's frame is a switch of some other
kind, 1 by default. What it is has not been found.

## Pads

The app's pad routine scales the first reading by the pad's calibration `thr`
(pad object + 10): below `thr` it maps to 0–336, from `thr` to 898 it maps
to 336–898. The result is cut to a window set by the two sensitivity
settings (two of them, both 5 by default: 239 to 839), and
goes through a curve to a velocity of 0–1023. A pad is on when that is not
zero and the second reading is above 59 for a few frames. It goes off when
the velocity falls to zero.

`thr` comes from `/root/data/PadCalibration.xml` (`PadCalibrationFile`): one element `PadCalibrationData` with attributes
`Pad01_Final` … `Pad16_Final` and the same for `Provisional1`–`3`, each
217–454. The file is written on the production line (`TMPadCalibration…`
classes) and is not in the update. Without it `thr` is 0, a resting pad
reads as 336, which is inside the window: every pad is held for ever, no hit
is heard, and the app blinks all the pads red.
`run.sh` writes one with 336 everywhere, with which a pad at rest is 0, a
hit begins at 336 and is at full velocity near 840.

A frame must not catch a value half written: 900 seen with only its low
byte in place is 132. The shim locks the frame for that.
The app's frame builder also shows the lamp layout of the app's frame: 32 RGB lamps
(ids `0x1f`–`0x3e`, 3 bytes each from byte 1) and 2-bit lamps in bytes
`0x61`–`0x6B`. With the panel live: encoder 0 moves the track
selection, its push opens TRACK MENU, encoders 2 and 3 change PITCH and
VELOCITY, and a mouse click acts as a touch.

Startup request (the startup object): `02 … | 0x6C: 05 04 | … CRC`.
`/dev/cdc_spi2.0` uses the same ioctl set with 4-byte replies: the touch
strip, below.

The updater (`iso/update`, with symbols) talks to the panel MCU's *update*
mode through `/dev/subucom_spi0.0` with plain `write()`/`read()`, a GPIO
handshake (`GpioHandshake::request_wait`) and CRC-16-CCITT
(`ErrorDitection::upd_crc_ccitt16_go8`). That is a different path from the
app's.
