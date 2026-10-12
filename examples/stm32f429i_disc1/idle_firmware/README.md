# Idle firmware (STM32F429I-DISC1)

Hardware-in-the-loop runs (`boardrunner trace`, and the passthrough and
record modes of FastDyn) execute the firmware in QEMU and forward its
peripheral accesses to the real board. The board itself runs this idle
firmware: it keeps the CPU out of the way and turns every peripheral
interrupt into a `bkpt` that FastDyn picks up and raises in QEMU.

## Flash it

Connect the board over its ST-LINK USB port, then:

```bash
./flash.sh            # flashes idlefirmware_f429.axf
```

`flash.sh` uses OpenOCD with `board/stm32f429disc1.cfg`; set
`BOARD_CFG` for another configuration and `OPENOCD` for another OpenOCD
binary. Flash it once; it stays on the board until something else is
flashed.

## Interrupt numbers

Each interrupt handler does `mov r0, <id>; bkpt`, where `<id>` is the NVIC
IRQ number (e.g. EXTI0 = 6, USART1 = 37), not the exception vector number (IRQ + 16); FastDyn
adds the 16. With vector numbers the board halts on the first interrupt and
QEMU raises the wrong one: peripheral accesses still work, but no interrupt
reaches the firmware. Check a build before flashing it:

```bash
arm-none-eabi-objdump -d build/idlefirmware.axf | grep -A3 '<EXTI0_IRQHandler>:' | grep -oE '#[0-9]+'   # #6
```

## Rebuild it

The build uses clang with the Arm GNU toolchain's headers and libraries
([arm-gnu-toolchain 13.3.rel1](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads),
`arm-none-eabi`):

```bash
sudo apt install -y clang llvm lld
make bc exec GCC_INSTALL=/path/to/arm-gnu-toolchain-13.3.rel1-x86_64-arm-none-eabi/   # -> build/idlefirmware.axf
cp build/idlefirmware.axf idlefirmware_f429.axf
```

`main.c` and `interrupt_server.c` are the firmware, `startup.s` the vector
table and `stm32_flash.ld` the memory layout.

## Test firmwares

`simple_tests/` holds small bare-metal test programs built from the same
tree, one per `TRAIN_*` define (`TRAIN_TIMER`, `TRAIN_GPIO`, `TRAIN_GPIO_INT`,
`TRAIN_USART`, `TRAIN_ADC_DMA`). With the define, `main()` runs that test
instead of idling, and the test's own interrupt handler replaces the
forwarding one. For example, the firmware of the hybrid `GPIO_INT` workload
(the user button B1 on PA0 raises EXTI0, whose handler toggles LD3):

```bash
make clean
make bc exec CFLAG_EXTRA=-DTRAIN_GPIO_INT GCC_INSTALL=/path/to/arm-gnu-toolchain-13.3.rel1-x86_64-arm-none-eabi/
cp build/idlefirmware.axf ../hybrid/GPIO_INT/firmwares/gpio_int.axf
make clean    # before building the idle firmware again
```
