# Idle firmware (STM32F769I-EVAL)

Hardware-in-the-loop runs (`boardrunner trace`, and the passthrough and
record modes of FastDyn) execute the firmware in QEMU and forward its
peripheral accesses to the real board. The board itself runs this idle
firmware: it keeps the CPU out of the way and turns every peripheral
interrupt into a `bkpt` that FastDyn picks up and raises in QEMU.

## Flash it

Connect the board over its ST-LINK USB port, then:

```bash
./flash.sh            # flashes idlefirmware_f769.axf
```

`flash.sh` uses OpenOCD with `board/stm32f7discovery.cfg` (OpenOCD has no STM32F769I-EVAL configuration; the F7 discovery one works over its ST-LINK); set
`BOARD_CFG` for another configuration and `OPENOCD` for another OpenOCD
binary. Flash it once; it stays on the board until something else is
flashed.

## Interrupt numbers

Each interrupt handler does `mov r0, <id>; bkpt`, where `<id>` is the NVIC
IRQ number (e.g. EXTI15_10 = 40, USART1 = 37), not the exception vector number (IRQ + 16); FastDyn
adds the 16. With vector numbers the board halts on the first interrupt and
QEMU raises the wrong one: peripheral accesses still work, but no interrupt
reaches the firmware. Check a build before flashing it:

```bash
arm-none-eabi-objdump -d build/idlefirmware.axf | grep -A3 '<EXTI15_10_IRQHandler>:' | grep -oE '#[0-9]+'   # #40
```

## Rebuild it

The build uses clang with the Arm GNU toolchain's headers and libraries
([arm-gnu-toolchain 13.3.rel1](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads),
`arm-none-eabi`):

```bash
sudo apt install -y clang llvm lld
make bc exec GCC_INSTALL=/path/to/arm-gnu-toolchain-13.3.rel1-x86_64-arm-none-eabi/   # -> build/idlefirmware.axf
cp build/idlefirmware.axf idlefirmware_f769.axf
```

`main.c` and `interrupt_server.c` are the firmware, `startup.s` the vector
table and `stm32_flash.ld` the memory layout.
