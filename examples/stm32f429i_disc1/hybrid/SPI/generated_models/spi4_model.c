// Device Model for SPI4
#include <fastdyn/device_model.h>
#include <stdlib.h>
#include <vio/vio.h>
#include <string.h>
#include <stdio.h>
#include <stdbool.h>

// Base address and register offsets for SPI4
#define SPI4_BASE_ADDR   0x40013400
#define SPI4_CR1_OFS     0x00
#define SPI4_CR2_OFS     0x04
#define SPI4_SR_OFS      0x08
#define SPI4_DR_OFS      0x0C
#define SPI4_I2SCFGR_OFS 0x1C

// Control Register 1 (CR1) bits
#define CR1_SPE          (1u << 6) // SPI Enable

// Status Register (SR) bits
#define SR_RXNE          (1u << 0) // Receive buffer not empty
#define SR_TXE           (1u << 1) // Transmit buffer empty

// Device state structure
typedef struct {
    // Memory-mapped registers
    uint32_t cr1;
    uint32_t cr2;
    uint32_t sr;
    uint32_t dr; // Shadow data register
    uint32_t i2scfgr;

    // SPI bus connection and state
    SPIBus *bus;
    bool bus_initialized;
    int active_cs_id; // Assumes a default CS line, e.g., 0

    // Debugging helper
    char debug_str[128];
    uint64_t base;
    const FdHost *host;
    const char *name;
} Spi4State;

/**
 * Inferred Register Functions:
 * - CR1: Used for configuration and enabling the peripheral (SPE bit).
 * - SR: Polled for TXE (transmit ready) and RXNE (receive ready) flags.
 * - DR: Writing initiates a transfer; reading retrieves data and clears RXNE.
 * - CR2/I2SCFGR: Acknowledged but have no side effects in this model.
*/

static uint64_t spi4_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc) {
    (void)pc;
    Spi4State *s = (Spi4State *)opaque;
    uint32_t offset = addr - s->base;
    uint64_t value = 0;

    switch (offset) {
        case SPI4_CR1_OFS:
            value = s->cr1;
            break;
        case SPI4_CR2_OFS:
            value = s->cr2;
            break;
        case SPI4_SR_OFS:
            value = s->sr;
            break;
        case SPI4_DR_OFS:
            value = s->dr;
            // Per hardware behavior, reading DR clears the RXNE flag.
            s->sr &= ~SR_RXNE;
            break;
        case SPI4_I2SCFGR_OFS:
            value = s->i2scfgr;
            break;
        default:
            snprintf(s->debug_str, sizeof(s->debug_str), "SPI4: Read from unhandled offset 0x%x", offset);
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", s->debug_str);
            break;
    }
    return value;
}

static void spi4_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc) {
    (void)pc;
    Spi4State *s = (Spi4State *)opaque;
    uint32_t offset = addr - s->base;

    switch (offset) {
        case SPI4_CR1_OFS:
            s->cr1 = value;
            break;
        case SPI4_CR2_OFS:
            s->cr2 = value;
            break;
        case SPI4_DR_OFS:
            // Only perform transfer if the peripheral is enabled (SPE=1)
            if ((s->cr1 & CR1_SPE) && s->bus_initialized) {
                // CORRECTION: Properly manage the Chip Select line around the transfer.

                // 1. Assert CS to select the slave (active low)
                api_spi_set_cs(s->bus, s->active_cs_id, 0);

                // 2. Perform the full-duplex transfer
                uint32_t received_data = api_spi_transfer(s->bus, (uint32_t)value);
                s->dr = received_data;

                // 3. De-assert CS to release the slave
                api_spi_set_cs(s->bus, s->active_cs_id, 1);

                // 4. Set RXNE flag to indicate new data has been received.
                s->sr |= SR_RXNE;
            }
            break;
        case SPI4_I2SCFGR_OFS:
            s->i2scfgr = value;
            break;
        default:
            snprintf(s->debug_str, sizeof(s->debug_str), "SPI4: Write to unhandled offset 0x%x", offset);
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", s->debug_str);
            break;
    }
}

static void *spi4_init(const FdDevice *dev, const char *config_json, const FdHost *host) {
    Spi4State *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->base = dev->ranges[0].base;
    s->host = host;
    s->name = dev->name;

    // By default, the transmit buffer is empty.
    s->sr = SR_TXE;
    s->active_cs_id = 0; // Assume we are controlling CS line 0

    // Initialize the SPI bus to connect with slave device models.
    s->bus = vio_spi_bus_init(config_json);
    if (!s->bus) {
        host->log(FD_LOG_LEVEL_ERROR, dev->name, "cannot create the SPI bus from the device configuration");
        free(s);
        return NULL;
    }
    if (s->bus->Slaves.num_slaves > 0) {
        s->bus_initialized = true;
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "SPI4: Model initialized and connected to bus.");
    } else {
        s->bus_initialized = false;
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "SPI4: Model initialized without slave devices.");
    }
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = spi4_init,
    .read = spi4_read,
    .write = spi4_write,
};
