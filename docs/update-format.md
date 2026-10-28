# The update file

`DJS1000.UPD` is the update the maker publishes. It is encrypted, and `scripts/setup.sh` opens it with a key that you
supply (see [your firmware and key](running.md#your-firmware-and-key)). Nothing of it, and no key, is kept in this repository.

Setup checks the file, opens it and unpacks the unit's system into `$DJS_HOME/root`, the root filesystem the emulator runs
the app in. The unit's own settings and per-unit values such as the MAC address are not part of an update.
