# Rules for device models

A test copy of BoardRunner's model_rules.md: the same structure and
markers, shorter text. The functions a model can call are the emulator's
host functions<!-- vio --> and the LibVIO API<!-- /vio -->.

## 1. The interface

Export `fastdyn_model` from `<fastdyn/device_model.h>`.

## 2. Addresses

`read` and `write` receive absolute guest addresses.

## 3. Configuration

- `config_json` holds the device's settings.<!-- vio --> A bus controller passes it
  to `vio_spi_bus_init()`.<!-- /vio -->

## 4. Stateful emulation over trace memorization

Never emit record-and-replay code.

<!-- vio -->
## 5. Observability and host I/O

Expose host interaction with the appropriate LibVIO API.
<!-- /vio -->
