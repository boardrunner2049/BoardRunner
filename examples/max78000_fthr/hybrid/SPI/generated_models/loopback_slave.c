// loopback
//
// Minimal stateful SPI slave model for the MAX78000 SPI loopback example.
// This model behaves like an external MOSI<->MISO wire loopback:
// while CS is active, each transfer returns the same value it received.
//
// LibVIO slave interface (<vio/slave.h>), one instance per slave:
//   - vio_spi_slave_init
//   - vio_spi_slave_set_cs
//   - vio_spi_slave_transfer
//
// Build:
//   boardrunner build-models loopback

#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include <vio/slave.h>

const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;

typedef struct {
    uint8_t regs[256];

    // Kept to follow the expected model structure. This device has no real
    // register-address phase, so we use this as a "first byte in frame" flag.
    bool    expect_reg_addr;
    uint8_t reg_ptr;

    bool    cs_active;
    bool    inited;

    uint32_t transfer_count;
    uint8_t  last_mosi;
    uint8_t  last_miso;
} spi_loopback_state_t;


// Load power-on defaults and clear transaction state.
static void load_defaults(spi_loopback_state_t *s)
{
    memset(s->regs, 0, sizeof(s->regs));

    s->expect_reg_addr = false;
    s->reg_ptr         = 0;

    s->cs_active       = false;
    s->transfer_count  = 0;
    s->last_mosi       = 0x00;
    s->last_miso       = 0x00;
}

// Lazy init guard.
void *vio_spi_slave_init(const char *name, const char *config_json)
{
    (void)name;
    (void)config_json;
    spi_loopback_state_t *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    load_defaults(s);
    s->inited = true;
    return s;
}

// REQUIRED callback: level 0 = CS active, level 1 = CS inactive.
void vio_spi_slave_set_cs(void *ctx, int level)
{
    spi_loopback_state_t *s = ctx;

    if (level == 0) {
        s->cs_active = true;
        s->expect_reg_addr = true;
        s->transfer_count = 0;
    } else {
        s->cs_active = false;
        s->expect_reg_addr = false;
    }
}

// REQUIRED callback: full-duplex SPI transfer.
// This loopback device immediately echoes the master's transmitted value
// back to the master while CS is active.
//
// The firmware uses 8-bit transfers, but returning the full 32-bit value
// keeps the model tolerant of wider future transfers.
uint32_t vio_spi_slave_transfer(void *ctx, uint32_t val)
{
    spi_loopback_state_t *s = ctx;

    if (!s->cs_active) {
        return 0x00000000u;
    }

    if (s->expect_reg_addr) {
        // No real command/register phase exists for this device; clear the
        // marker after the first transfer of the frame.
        s->expect_reg_addr = false;
    }

    s->last_mosi = (uint8_t)(val & 0xFFu);
    s->last_miso = s->last_mosi;

    // Keep a circular byte history to maintain explicit statefulness.
    s->regs[s->reg_ptr] = s->last_mosi;
    s->reg_ptr = (uint8_t)(s->reg_ptr + 1);
    s->transfer_count++;

    // Echo input to output: emulates MOSI wired directly to MISO.
    return val;
}

