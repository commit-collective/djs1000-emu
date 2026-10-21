# Emulation: what is stood in for, and the state

What `djsdev.c` stands in for, and why:

| what | stand-in | without it |
|---|---|---|
| `/dev/backlight`, `/dev/gpiodrv` | `/dev/zero` (the app polls `gpiodrv` ~500x/s) | `BacklightManager` crashes in its own error message (passes a line number to a `%s`) |
| `/dev/subucom_spi0.1` (panel), `/dev/cdc_spi2.0` (the touch strip) | the driver's behaviour, from `subucom_spi.c`: timer, reply on `read()`, `POLLIN` | `main()` waits forever for the panel handshake (its startup object) |
| panel reply | idle frame, identifier `0x01`, CRC | `didRecievePanelComData - invalid identifier` / `UIThread (IN) - CRC Error` |
| `snd_pcm_open("hw:ak4452audio,N")` | ALSA `null` (or `$DJSDEV_PCM`), reporting exactly 2 channels like the board's stereo devices | the device does not open and startup never completes. With `null`'s own 1–32 channels the audio thread crashes, see [power-standby.md](power-standby.md) |
| `socket(AF_PACKET, SOCK_RAW, ETH_P_IP)` (`UDPRecvManager`) | a socket that receives the Pro DJ Link broadcasts of the host's network (see below). `bind`/`setsockopt` succeed | needs CAP_NET_RAW. The thread carries on with -1 and crashes |
| `snd_pcm_readi` on the input | the sound the virtual deck sends, as the 24-bit-in-32 samples the app expects. Silence without it | |
| `snd_pcm_hw_params_set_format` on the board's devices | only S24_LE is accepted (24 bits in the low three bytes of a 32-bit word), as on the unit, so the app settles on it there too: 64-frame periods, 2 of them | `null` accepts 32-bit float, which the app tries first: the app works, but what a mod sees in the sound path is not what it would see on a unit |
| `snd_pcm_writei` on the outputs | the master's is paced to 44100 frames a second, and both outputs' sound is kept for the virtual deck | `null` takes sound as fast as it is given, so the app's audio thread spins: a core and a half burnt, startup 3 minutes instead of 30 s |
| `/root/data/PadCalibration.xml` (the unit's data partition) | made by `run.sh`: 336 for every pad | the app takes every pad as held for ever and blinks them all red, see [panel-protocol.md](panel-protocol.md) |
| `/proc/udev_usb1`, `/proc/udev_usbctn1` (Pioneer's `fs/proc/udev_usb.c`, `udev_usbctn.c`: system-wide message queues udev writes to, a message kept until some reader takes it, one beginning with `0` emptying the queue) | a file in the guest's `/tmp` per queue, shared by every process (`init.sh`'s shell writes what udev would), handed to the app through a socket pair. `umount()` succeeds | no drive: "Save To: ---" |

The unit's internal storage (the eMMC, a FAT volume on `/mnt/emmc`: the factory samples and projects) is a folder of the
host too, `$DJS_EMMC`, bound on `/mnt/emmc` by `run.sh` when it is set (`start.py` passes it on). It holds a `PIONEER DJ SAMPLER`
folder, as the stick does. The app lists its projects under OPEN, Internal. Without `$DJS_EMMC`, `/mnt/emmc` is empty. The factory
content is Pioneer's and the sample packs' makers': copy it off a unit of your own and keep it out of this repository.

The USB drive is the host folder `~/djs/usb` (`$DJS_USB`), bound on
`/media/usb1/sda1` by `run.sh`. The app (`UsbMountManager`) takes `mount <path>`, `umount <path>`, `do_umount <n> <path>`
(which it writes itself for USB STOP), and `connect` / `disconnect` on the
second queue. On mount it creates `PIONEER DJ SAMPLER/{Projects,Samples,
Scenes}` there. SAVE writes `Projects/<name>.prj` and `System/recent.list`.
`usb 0` / `usb 1` on the command pipe unplug and plug it, through
`init.sh unplug` / `plug`, which do what udev does (`connect`, the stick's
autoexec, then `mount`). `DJSDEV_USB=0` starts without it. As on the unit, an
app started again while the stick is in is told nothing of it unless the
queues are written to again (a patch that restarts the app has to). After a
stick's `autoexec.sh` returns, `init.sh` warns if a process is still in
`/mnt/iso`: on the unit that image could then not be unmounted, and the
stick would stay busy (USB STOP hangs). The unit's console, where such a
process may send its output, is `$DJS_HOME/run/console.log`. The unit's settings partition, `/root/data`, is
`root/data` in the rootfs, or the folder `$DJS_DATA`: an empty one is a unit
as it left the factory.

## A stick's autoexec.bin

On the unit, udev's rule for a USB stick (`12-usb-memory-auto-mount.rules`)
mounts it and runs `/root/pdj/decrypt_autoexec.sh <mount point>` before it
tells the app of the mount. If the stick holds `autoexec.bin`, that script
opens it as a cryptoloop image with the unit's key
(`/usr/local/pdj/aes256.key`, the same key and cipher as the update file,
without the trailer), mounts it on `/mnt/iso`, and runs its `autoexec.sh`
with the stick's mount point, as root. Nothing is written to the unit.

The emulator does the same with the USB folder's `autoexec.bin`:

- `run.sh` opens it at start (`tools/decrypt_upd.py --raw`, a loop device
  would need root) and puts what it holds on `/mnt/iso`. It must hold an ISO
  9660 file system. The names come out as Linux shows them, in lower case.
- `scripts/guest/init.sh` runs inside the root filesystem in place of the end
  of `apl_start`: it runs the stick's `autoexec.sh` and then starts the app,
  which is the order on a unit switched on with the stick in. `usb 1` on the
  command pipe runs it again before the mount is announced, as plugging the
  stick in does.
- The app is started once and not watched on the unit, so an autoexec may
  stop it and start it again. The emulator ends only when no app has run for
  five seconds. `pidof` and `killall` in `/opt/djsemu/bin` find the unit's
  programs, which `/proc` here names `qemu-arm-static`.
- With extra qemu arguments (`-g` for gdb) `run.sh` starts the app alone, as
  before.

Stock behaviour is unchanged by all this: the regression session comes out
the same, with no patch and with one that does nothing.

## The display

The app draws through X. `run.sh` starts `Xvfb` for it when that is
installed (display `:77` or the next free one, gone when the emulator
stops), so that no window shows. `DJS_WINDOW=1` puts the window on
`$DISPLAY`. That window must not be closed: on the request the app starts to
quit and hangs half shut down, its process still there. The shim drops the
request (`WM_DELETE_WINDOW` in `XNextEvent`, and the `wmclose` command sends one
to check), and `start.py` tells a live emulator from a stuck one by the
sound that arrives on the deck link, and restarts a stuck one.

With all of these the app runs without crashing (3+ minutes), panel frames
flow, `SystemManager` is constructed, and `XOpenDisplay(":0")` (WSLg)
succeeds from `main()`.

Still failing, harmlessly so far: `/dev/mem` (`readl error`), `/dev/mmcblk1`
(eMMC) and `/proc/g_midi`, `/dev/snd/seq`.

The network and Pro DJ Link. The app brings its Pro DJ Link stack up only
when it thinks the Ethernet cable is in: `WirelessLanMonitor::
checkEtherLanConnection` asks the Ethernet driver, on "eth0",
with the device-private ioctls `0x89fc`, `0x89fd` and `0x89fe` (the last
answers through the ifreq's data pointer: non-zero for a cable), and
`NetworkManager`'s constructor sets up with `0x89ff`. The host
kernel cannot take those (the app sees ENOTTY: no cable, "PLAYER" greyed out
on the home screen, no link), so the shim answers them: cable in. With that
the app starts its UDP threads (a message "UDP SEND START"), takes the host's
eth0 address and MAC, and does what a unit does: it announces itself on UDP
50000 as "DJS-1000" (a hello, the three claim stages, then keep-alives) with
its PLAYER No., 1 by default. It binds UDP 50000-50002 itself (sharing them),
so the broadcasts of the host's network and of its loopback reach it as they
would on a unit, and a deck on the network, with a player number other than
its own, is a linked player: SYNC and MASTER work instead of "No LINKED
Players found" (a deck with the unit's own number is a clash, and none is
linked).

The shim also gives every `AF_PACKET` socket the app (or anything in it,
a mod) opens the Pro DJ Link broadcasts as the packets it would have read on
a unit: it listens on the host side to UDP 50000 (a deck's keep-alive),
50001 (beats) and 50002 (a deck's status), and hands each datagram on as the
whole Ethernet frame (zero MAC, IPv4 from the sender's address and port to
255.255.255.255, UDP without a checksum) for a `SOCK_RAW` socket, the IP
packet alone for a `SOCK_DGRAM` one. (The app's own `AF_PACKET` socket is for
the PC link over USB Ethernet, not for Pro DJ Link. A mod's can read the
decks' packets.) Decks can be fake ones sending to the loopback broadcast
(127.255.255.255, as deckbench does, which `start.py` runs). Under WSL2 the network is NAT: real decks on the physical
network are not seen unless WSL uses mirrored networking or a bridge.
The regression's reference was recorded again with this (the PLAYER box is
no longer greyed out).

What was found of the app's Pro DJ Link (firmware 1.22), for going on:

- The shim logs which UDP ports the app binds (it holds two sockets on each
  of 50000, 50001 and 50002) and, once per kind, what it receives there:
  50000 the claim packets (types 0x00, 0x02, 0x04) and keep-alives (0x06,
  0x0a), 50001 beats (0x28, 96 bytes), 50002 statuses (0x0a, 292 bytes). So a
  fake deck's packets do arrive.
- What the unit sends: a hello (0x0a), the claim stages and then keep-alives,
  as "DJS-1000", player 1 (`PLAYER No.`), with the host's address and MAC. And
  a short 36-byte packet of type 0x10 on 50002. And, to a deck it has heard,
  a status (0x0a, 292 bytes) to the deck's own address, UDP 50002 (not to the
  broadcast, so a listener must be bound to the deck's address, not any: the
  fake decks do). With a deck as master it asks it to hand over with a 0x26
  request to 50001 and the deck answers with a 0x27. The shim logs what the
  app sends on 50000-50002, once per kind. The unit's own datagrams, which
  the host's network brings back, are not passed to the app's packet sockets
  (the unit would be a linked player of its own network, and the "No LINKED
  Players found" message would never show).
- Its choice of the deck to sync to (its sync-target routine) goes over six stored copies of status packets (292 bytes,
  at +0x16c8 + n * 0x124 of the network manager), takes the player whose
  flags byte (0x89) & 0x5c is 0x5c (playing, synced, on air, and bit 2) with
  the lowest sync counter (0x84), failing that 0x54, 0x4c, 0x44, and last any
  that plays. The master bit (0x20) is not what it looks at there.
  `TempoController::beatsyncController` is the state machine of
  the SYNC and MASTER buttons.
- What makes the unit follow a deck: its status packet must be built like a
  CDJ's. The fake decks' status packets lacked the header after the name
  (01, the subtype 03, the player, the length that follows at 0x22) and the
  "master valid" word at 0x90 (0x8000 for a rekordbox track: "only then are
  tempos from this player accepted as master", as the analysis says). With
  them the unit follows the deck (MASTER PLAYER n, its BPM, the master's beat
  in its squares, SYNC lit) and its MASTER is a hand-off. The fake decks also
  send the pitch four times (0x8c, 0x98, 0xc0, 0xc4), the play mode (0x9d),
  the beat in the track (0xa0) and the nexus byte (0xcc), as a CDJ does.
- A deck taking the master role from the unit: it sends the 0x26 request
  (to 50001), the unit answers 0x27 (accept) and puts the deck's number in its
  hand-off field (0x9f) if the deck's status says it is synced (flag 0x10).
  When the deck's status then says it is the master the unit stops being
  one, provided that status has bit 7 of the flags (0x80) set. A real player
  has it (Beat Link's status starts from 0x84, the unit's own is 0x84 or
  0xa4), the analysis calls it unknown. Without it the unit stayed a master.

Audio as configured by the app: 44.1 kHz, 64-frame periods x 2.
`hw:ak4452audio,1` ("master") 2 channels out. `hw:ak4452audio,0`
("headphone") 2 out, 2 in.
