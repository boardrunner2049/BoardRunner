# Host functions for device models

Provided by the emulator<!-- vio -->, not by LibVIO<!-- /vio -->. A test copy of the
contract's host_api.md.

## Logging

```c
host->log(FD_LOG_LEVEL_INFO, dev->name, "configured %d channels", n);
```

## Interrupts

```c
void qemu_plugin_raise_irq(int irq, int secure);
```

## Time and timers

```c
void qemu_plugin_timer_alarm(uint64_t timer_fd, uint64_t delay_ns);
```
