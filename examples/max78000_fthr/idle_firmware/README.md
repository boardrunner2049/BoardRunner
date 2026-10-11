# Idle firmware (MAX78000FTHR)

Hardware-in-the-loop runs (`boardrunner trace`, and the passthrough and
record modes of FastDyn) execute the firmware in QEMU and forward its
peripheral accesses to the real board. The board itself runs this idle
firmware: it keeps the CPU out of the way and turns every peripheral
interrupt into a `bkpt` that FastDyn picks up and raises in QEMU.

## Flash it

The MAX78000 needs the OpenOCD of Analog Devices' MSDK. Connect the board
over its USB port (CMSIS-DAP), then:

```bash
MAXIM_PATH=/path/to/MaximSDK ./flash.sh    # flashes idle_firmware_max78000.elf
```

Flash it once; it stays on the board until something else is flashed.

## Interrupt numbers

Each interrupt handler hands FastDyn the NVIC IRQ number, not the exception
vector number (IRQ + 16); FastDyn adds the 16. With vector numbers QEMU
raises the wrong interrupt: peripheral accesses still work, but no interrupt
reaches the firmware.

## Rebuild it

With the MSDK installed:

```bash
make MAXIM_PATH=/path/to/MaximSDK          # -> build/max78000.elf
cp build/max78000.elf idle_firmware_max78000.elf
```

`main.c` and `interrupt_server.c` are the firmware; `Makefile` and
`project.mk` are the MSDK's project files (board `FTHR_RevA`).
