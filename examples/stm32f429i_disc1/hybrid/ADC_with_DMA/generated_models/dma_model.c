#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <fastdyn/device_model.h>
#include <stdlib.h>
#include <vio/vio.h>

// Base address for DMA2
#define DMA2_BASE 0x40026400

// Register Offsets from DMA2_BASE
#define DMA_LISR   0x00
#define DMA_HISR   0x04
#define DMA_LIFCR  0x08
#define DMA_HIFCR  0x0C
#define DMA_S0CR   0x10
#define DMA_S0NDTR 0x14
#define DMA_S0PAR  0x18
#define DMA_S0M0AR 0x1C
#define DMA_S0M1AR 0x20
#define DMA_S0FCR  0x24

// Stream Configuration Register (SxCR) bits
#define DMA_SxCR_EN     (1U << 0)
#define DMA_SxCR_TCIE   (1U << 4)
#define DMA_SxCR_CIRC   (1U << 8)
#define DMA_SxCR_MINC   (1U << 10)
#define DMA_SxCR_PSIZE_SHIFT 11
#define DMA_SxCR_MSIZE_SHIFT 13

// Low Interrupt Status/Clear Register (LISR/LIFCR) bits for Stream 0
#define DMA_LISR_TCIF0  (1U << 5)

// DMA2 Stream 0 Interrupt Vector
#define DMA2_STREAM0_IRQ 72

// State structure for the DMA2 peripheral
typedef struct DMAState {
    uint32_t lisr;
    uint32_t hisr;

    // We only model Stream 0 based on traces
    uint32_t s0cr;
    uint32_t s0ndtr;
    uint32_t s0par;
    uint32_t s0m0ar;
    uint32_t s0fcr;

    // Model-specific state for circular mode operation
    uint32_t s0ndtr_initial;
    uint32_t s0m0ar_initial;
    uint64_t base;
    const FdHost *host;
    const char *name;
} DMAState;

// Forward declaration for the DMA request handler
static void dma_stream0_request_handler(void *opaque);

/**
 * @brief Emulates reads from the DMA2 memory-mapped registers.
 */
static uint64_t dma2_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc) {
    (void)pc;
    DMAState *s = (DMAState *)opaque;
    uint32_t offset = addr - s->base;
    uint64_t value = 0;

    switch (offset) {
        case DMA_LISR:
            value = s->lisr;
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 READ: LISR -> 0x%08X\n", value);
            break;
        case DMA_S0CR:
            value = s->s0cr;
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 READ: S0CR -> 0x%08X\n", value);
            break;
        case DMA_S0NDTR:
            value = s->s0ndtr;
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 READ: S0NDTR -> %u\n", value);
            break;
        case DMA_S0PAR:
            value = s->s0par;
            break;
        case DMA_S0M0AR:
            value = s->s0m0ar;
            break;
        default:
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 READ: Unhandled address 0x%08X\n", (unsigned int)addr);
            break;
    }
    return value;
}

/**
 * @brief Emulates writes to the DMA2 memory-mapped registers.
 */
static void dma2_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc) {
    (void)pc;
    DMAState *s = (DMAState *)opaque;
    uint32_t offset = addr - s->base;

    switch (offset) {
        case DMA_LIFCR:
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 WRITE: LIFCR <- 0x%08X\n", (uint32_t)value);
            // Clear the flags specified by the write value
            s->lisr &= ~((uint32_t)value);
            break;
        case DMA_S0CR:
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 WRITE: S0CR <- 0x%08X\n", (uint32_t)value);
            // If stream is being enabled for the first time
            if ((value & DMA_SxCR_EN) && !(s->s0cr & DMA_SxCR_EN)) {
                // Save initial values for circular mode
                s->s0ndtr_initial = s->s0ndtr;
                s->s0m0ar_initial = s->s0m0ar;
                s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2: Stream 0 enabled. NDTR=%u, M0AR=0x%08X\n",
                          s->s0ndtr_initial, s->s0m0ar_initial);
            }
            s->s0cr = value;
            break;
        case DMA_S0NDTR:
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 WRITE: S0NDTR <- %u\n", (uint32_t)value);
            s->s0ndtr = value;
            break;
        case DMA_S0PAR:
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 WRITE: S0PAR <- 0x%08X\n", (uint32_t)value);
            s->s0par = value;
            break;
        case DMA_S0M0AR:
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 WRITE: S0M0AR <- 0x%08X\n", (uint32_t)value);
            s->s0m0ar = value;
            break;
        default:
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2 WRITE: Unhandled address 0x%08X with value 0x%llX\n",
                      (unsigned int)addr, value);
            break;
    }
}

/**
 * @brief Handles a DMA request from a peripheral for Stream 0.
 * This function performs the actual data transfer.
 */
static void dma_stream0_request_handler(void *opaque) {
    DMAState *s = (DMAState *)opaque;
    // 1. Check if the stream is enabled and has data to transfer
    if (!(s->s0cr & DMA_SxCR_EN) || s->s0ndtr == 0) {
        return;
    }

    // 2. Determine transfer size (only 16-bit implemented as per traces)
    uint32_t psize_bits = (s->s0cr >> DMA_SxCR_PSIZE_SHIFT) & 0x3;
    uint32_t msize_bits = (s->s0cr >> DMA_SxCR_MSIZE_SHIFT) & 0x3;
    int transfer_size = 2; // Default to 16-bit (half-word)

    if (psize_bits != 1 || msize_bits != 1) {
         s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "DMA2 WARN: Only 16-bit transfers are modeled.\n");
    }

    // 3. Perform the peripheral-to-memory transfer
    uint8_t buffer[4];
    qemu_plugin_read_memory(s->s0par, buffer, transfer_size);
    qemu_plugin_write_memory(s->s0m0ar, buffer, transfer_size);

    // 4. Update state: increment memory address and decrement counter
    if (s->s0cr & DMA_SxCR_MINC) {
        s->s0m0ar += transfer_size;
    }
    s->s0ndtr--;

    // 5. Check for transfer completion
    if (s->s0ndtr == 0) {
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "DMA2: Stream 0 transfer complete.\n");
        s->lisr |= DMA_LISR_TCIF0;

        // Raise interrupt if enabled
        if (s->s0cr & DMA_SxCR_TCIE) {
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2: Raising IRQ %d.\n", DMA2_STREAM0_IRQ);
            qemu_plugin_raise_irq(DMA2_STREAM0_IRQ, false);
        }

        // Handle circular vs. normal mode
        if (s->s0cr & DMA_SxCR_CIRC) {
            // Reload for next round
            s->s0ndtr = s->s0ndtr_initial;
            s->s0m0ar = s->s0m0ar_initial;
            s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "DMA2: Circular mode reload. NDTR=%u\n", s->s0ndtr);
        } else {
            // Disable stream in normal mode
            s->s0cr &= ~DMA_SxCR_EN;
        }
    }
}


/**
 * @brief Initializes the DMA2 device model state and registers its stream handler.
 */
static void *dma2_init(const FdDevice *dev, const char *config_json, const FdHost *host) {
    (void)config_json;
    DMAState *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->base = dev->ranges[0].base;
    s->host = host;
    s->name = dev->name;

    // The peripheral triggering the DMA (the ADC) requests DMA2 Stream 0.
    api_dma_register_stream(2, 0, dma_stream0_request_handler, s); // DMA2, Stream 0

    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "DMA2 device model initialized and Stream 0 handler registered.\n");
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = dma2_init,
    .read = dma2_read,
    .write = dma2_write,
};
