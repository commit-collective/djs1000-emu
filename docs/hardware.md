# Hardware and software, as read from the firmware

## Hardware

- Freescale i.MX6 (SABRE-SD based), NAND via GPMI, U-Boot 2009.08, Linux
  3.0.101 (Freescale LTIB BSP). Pioneer project "EP113",
  `ep113_2017_pad-player-mid`.
- NAND partitions: `boot` 3M, `reserve1` 1M, `env` 1M, `kernel_a`/`kernel_b`
  10M each, `rootfs` 32M, `pdj` 20M, `data` 20M (UBI), `reserve2` 20M,
  `data_raw` 3M, `reserve3` 10M, `misc` 118M, `reserve4` 8M.
- Console `ttymxc0` at 115200 (connector CN1401). U-Boot env flags
  seen in `apl_start`: `telnetd=on` starts telnetd, `aplstart=off` stops the
  app from starting, `printk=on` keeps kernel logging on the console.
- Screen: 800x480 RGB565 (`logo_pioneerdj.rgb565`, 768000 bytes, is written
  straight to `/dev/fb0`). The app itself draws through **X11** (JUCE).

## The application

- `/root/pdj/EP113_Main_R`: 12 MB ARM ELF, ARMv7-A + NEON, soft-float ABI,
  glibc 2.13, stripped, JUCE. Started by `rc.local` → `/root/pdj/apl_start`
  (cwd `/root/pdj`).
- Links: X11/Xext, ALSA, freetype, ICU 51, tcmalloc, `libcld`. Not the Vivante
  GPU libraries.
- Board devices it opens: `/dev/gpiodrv`, `/dev/subucom_spi0.1` (panel MCU),
  `/dev/cdc_spi2.0` (the touch strip), `/dev/backlight`, `/dev/din_midi`,
  `/dev/ttymxc1`.
- Its SIGSEGV handler writes `/mnt/debug/SIGSEGV.txt` and dumps state there,
  then tries to attach `gdbserver`.

## Pioneer's drivers (GPL sources)

`pioneerdj_djs.tar.gz` → `BUILD/linux-3.0.101/arch/arm/mach-mx6/`:
`subucom_spi.c/.h` (panel), `cdc_spi.c/.h`, `gpiodrv.c/.h`, `midi_thru.c`,
`board-mx6q_sabresd.c` (board wiring). Extracted in WSL at `~/djs/gpl/`.
