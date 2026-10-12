# Rules for device models

A device model emulates one peripheral for FastDyn's elder handler (model
ABI v2). It is a shared library built from C. The functions a model can call
are the emulator's host functions<!-- vio --> and the LibVIO API<!-- /vio -->.

## 1. The interface

The model includes `<fastdyn/device_model.h>` and exports one descriptor that
points at its functions:

```c
static void *my_init(const FdDevice *dev, const char *config_json, const FdHost *host);
static uint64_t my_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc);
static void my_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc);

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = my_init,
    .read = my_read,
    .write = my_write,
    /* optional: .interrupt and .serve, see section 5 */
};
```

- The function signatures must match exactly; the compiler rejects a
  mismatch (e.g. a `read` without the `pc` argument). Never cast a function
  to make it fit.
- `init` returns a pointer to the instance state. FastDyn passes it back as
  `opaque` to every other function. Returning NULL refuses the
  configuration and FastDyn stops.
- The functions have unique names of your choice; only `fastdyn_model` is
  exported. The names do not have to match the device's TOML key.

## 2. Addresses

`read` and `write` receive **absolute guest addresses**, not offsets. A read
of the register at offset 0x08 of a peripheral at 0x40022000 arrives as
`addr = 0x40022008`.

Decode registers as offsets from the base address the device was given,
never from a hard-coded base:

```c
s->base = dev->ranges[0].base;        /* in init */
switch (addr - s->base) {             /* in read and write */
    case 0x00: /* first register  */ ...
    case 0x08: /* second register */ ...
}
```

If the device has several address ranges (`dev->range_count > 1`), find the
range that contains `addr` and subtract that range's base. The trace data
shows absolute addresses; use them to infer the register layout, then
express registers as offsets.

## 3. Instance state

Keep **all** state in the struct returned by `init`, never in globals. One
model library can serve several devices of the same kind (for example USART2
and USART3, each with its own base address and IRQ), and each device gets its
own instance.

## 4. Configuration

- `dev` gives the device's name (`dev->name`), address ranges and IRQs.
- `config_json` holds the device's own settings from its TOML table, as a
  JSON object.<!-- vio --> A bus controller passes it unchanged to
  `vio_spi_bus_init()` or `vio_i2c_bus_init()`, which create the bus and its
  slave devices from the `slaves` list (see the SPI and I2C bus functions).<!-- /vio -->
- Do not hard-code values that come from the configuration.

## 5. Interrupts

- **Raising** an interrupt: `qemu_plugin_raise_irq(IRQn + 16, 0)`, where IRQn
  is the device's interrupt number from the reference manual (Cortex-M
  exception numbers are IRQn + 16; the second argument means non-secure).
- **Being told** about interrupts: the optional `.interrupt(opaque, irq)` and
  `.serve(opaque, irq)` are called when the CPU takes or returns from one of
  the device's own interrupts, the ones in its TOML `irq` list. `irq` is the
  Cortex-M exception number (IRQn + 16).

## 6. Stateful emulation over trace memorization

You must implement a dynamic, stateful model. The trace data is EVIDENCE for
reverse-engineering the register logic; it is NOT a lookup table to copy
from.

- Never emit "record-and-replay" code that hardcodes return values from the
  trace (e.g., `if (addr == X && count == N) return Y;`). Such code only works
  for the exact execution that was recorded and breaks on any other run.
- DO maintain a state struct whose fields represent register values.
- DO update state based on firmware writes at runtime (e.g., set/clear bits
  via masking when the firmware writes to a control register).
- DO derive read return values from current state, not from trace constants.
- DO keep the logic minimal: only implement behavior the trace evidence
  supports. Do not invent complex state machines, timers, or hardware
  features beyond what the trace implies. However, you SHOULD use your
  knowledge of the peripheral's reference manual for **bit field semantics
  only**: which bits within a register are read-only vs read-write, what
  individual fields represent (e.g. status flags, line state), and reset
  values. The trace is AUTHORITATIVE for register offsets, addresses, and
  runtime values; never override trace-derived offsets with reference manual
  memory maps. The reference manual helps you interpret WHY a bit behaves a
  certain way (e.g. a bit is read-only because it reflects hardware line
  state and must not be echoed from software writes).

## 7. Callbacks you register

Any function you register with the emulator (e.g. `qemu_plugin_timer_new_ns`)
<!-- vio -->or with LibVIO (e.g. `api_signal_register`, `api_dma_register_stream`)
<!-- /vio -->**must exactly match** the expected signature, and it receives the
`opaque` pointer you passed at registration. Accept that parameter and cast it
to your state:

```c
static void my_timer(void *opaque) {
    MyState *s = opaque;   /* the pointer you registered */
    ...
}
```

Never write an empty parameter list (`static void my_timer()`), and never
cast a function pointer to hide a type mismatch.

## 8. Logging

Log through the host: `host->log(level, dev->name, "format", ...)` with
`FD_LOG_LEVEL_DEBUG` ... `FD_LOG_LEVEL_ERROR`. Messages appear in FastDyn's
log as `fastdyn.<device>`, and its `-q` / `-v` options apply. Keep `host` and
the name in your state if you log outside `init`. Do not use `printf`.
Nothing may be logged on every register access unless it is at DEBUG level.

## 9. Timing

Timer callbacks run only at translation-block boundaries. For compare-match
or timeout logic, also check the condition in the read callback of the
register the firmware polls (see "Time and timers" in the host functions).

<!-- vio -->
## 10. Observability and host I/O

If the peripheral's firmware-level behavior implies interaction with an
external entity (e.g., receiving characters on a serial line, toggling
user-visible outputs, reading sensor data from an external bus), the model
MUST expose that interaction to the host using the appropriate LibVIO API
(PTY for serial streams, FIFO for generic byte pipes, TAP for network frames,
I2C/SPI buses for attached devices, etc.). Infer which API to use from the
register semantics and trace patterns; do not ask the user. The goal is to
make the emulated peripheral observable and interactive from the host side
wherever the real hardware would have been observable and interactive to a
user or external system.

## 11. Inter-peripheral communication

If the peripheral interacts with other hardware blocks at runtime (e.g.,
triggering a DMA transfer after a conversion completes, raising a signal line
that another peripheral listens on, or sharing an IRQ), express that
relationship using LibVIO's inter-peripheral APIs (`api_dma_request`,
`api_dma_register_stream`, `api_signal_set`, `api_signal_register`, etc.).

Do NOT call into another peripheral model's code. All cross-peripheral
interaction MUST go through the shared APIs so that models remain
independently replaceable.
<!-- /vio -->
