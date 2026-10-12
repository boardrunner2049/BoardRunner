# SD card (FatFs) (STM32F769I-EVAL, hybrid)

ST's FatFs_uSD application: it mounts the SD card, creates `STM32.TXT`, writes "This is STM32 working with FatFs" and reads it back.

Only part of the hardware is modeled: `sdmmc1_model.c`: SDMMC1, backed by the disk image `sdcard.img` in the run directory.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Power the board (its external 5 V supply), connect its ST-LINK USB port and
flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

Create a FAT32 disk image once, run, then look at the file:

```bash
dd if=/dev/zero of=sdcard.img bs=1M count=64
mkfs.fat -F 32 -S 512 -n SDCARD sdcard.img
```

```bash
boardrunner run -c sdcard_config.toml    # Ctrl-C after about 30 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
mdir -i sdcard.img ::   # (mtools) STM32.TXT is on the card
mtype -i sdcard.img ::STM32.TXT   # This is STM32 working with FatFs
```
