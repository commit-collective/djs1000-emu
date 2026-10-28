# The update file

`DJS1000.UPD` is the update the maker publishes. It is encrypted, and `scripts/setup.sh` opens it with a key that you
supply (see [your firmware and key](running.md#your-firmware-and-key)). Nothing of it, and no key, is kept in this repository.

- The body is an encrypted disk image, followed by a short trailer that names the version (`LIVESAMPLER1.22`) and carries a
  checksum of the body. `tools/decrypt_upd.py` checks the trailer and decrypts the body with your key, which gives an ISO 9660
  volume.
- In the volume: the bootloader, the Linux kernel with the installer's initial ramdisk, the root filesystem as archives, the
  SquashFS images of `/usr/bin`, `/usr/lib` and `/usr/share`, the application (`/root/pdj`), the panel's microcontroller
  firmware, the bootloader's environment file, and the installer.
- Not in it: the user data volume (`/root/data`, the unit's settings, which an update backs up and restores) and per-unit
  values such as the MAC address.

`scripts/setup.sh` unpacks these into `~/djs/root`, the root filesystem the emulator runs the app in.
