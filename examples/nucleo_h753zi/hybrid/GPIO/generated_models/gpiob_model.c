// Device Model for GPIOB
//
// Fix for the observed mismatch:
// - The firmware trace addresses are absolute (0x580204xx).
// - Many emulation frameworks pass either absolute addresses OR offsets into the MMIO callback.
// - If the model only matches offsets but receives absolute addresses, reads fall through -> 0,
//   and firmware RMW writes become tiny (e.g., 0x3 instead of 0xC3).
// This model normalizes both address forms to a base-relative offset before decoding.
//
// Observed registers:
//   MODER   (0x00)  R/W
//   OTYPER  (0x04)  R/W
//   OSPEEDR (0x08)  R/W
//   PUPDR   (0x0C)  R/W
//   ODR     (0x14)  R/W (read in loops)
//   BSRR    (0x18)  W   (set/reset affects ODR)

#include <fastdyn/device_model.h>

#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

#define GPIOB_BASE_ADDR      0x58020400ULL
#define GPIOB_MMIO_SPAN      0x400ULL  // generous decode window

#define GPIOB_MODER_OFF      0x00
#define GPIOB_OTYPER_OFF     0x04
#define GPIOB_OSPEEDR_OFF    0x08
#define GPIOB_PUPDR_OFF      0x0C
#define GPIOB_ODR_OFF        0x14
#define GPIOB_BSRR_OFF       0x18

typedef struct {
    uint32_t MODER;
    uint32_t OTYPER;   // only low 16 bits meaningful
    uint32_t OSPEEDR;
    uint32_t PUPDR;
    uint32_t ODR;      // only low 16 bits meaningful
    uint64_t base;      /* the device's base address, from dev->ranges[0].base */
    const FdHost *host;
    const char *name;
} gpiob_state_t;


static inline hwaddr gpiob_norm_off(hwaddr addr)
{
    // Accept either absolute MMIO addresses or already-normalized offsets.
    if ((uint64_t)addr >= GPIOB_BASE_ADDR && (uint64_t)addr < (GPIOB_BASE_ADDR + GPIOB_MMIO_SPAN)) {
        return (hwaddr)((uint64_t)addr - GPIOB_BASE_ADDR);
    }
    return addr;
}

static inline uint32_t mask_for_size(unsigned size)
{
    if (size >= 4) return 0xFFFFFFFFu;
    return (uint32_t)((1ULL << (size * 8)) - 1ULL);
}

static inline uint32_t apply_partial_write32(uint32_t oldv, hwaddr rel_off, uint64_t value, unsigned size)
{
    if (size >= 4) {
        return (uint32_t)value;
    }
    uint32_t m = mask_for_size(size);
    unsigned shift = (unsigned)((rel_off & 0x3) * 8);
    uint32_t w = (uint32_t)(value & m);
    uint32_t mask = (m << shift);
    return (oldv & ~mask) | (w << shift);
}

static inline uint64_t read_sized_u32(uint32_t v, unsigned size, hwaddr rel_off)
{
    if (size >= 4) return (uint64_t)v;
    uint32_t m = mask_for_size(size);
    unsigned shift = (unsigned)((rel_off & 0x3) * 8);
    return (uint64_t)((v >> shift) & m);
}

static void dbg(gpiob_state_t *s, const char *msg, hwaddr rel_off, uint64_t val, unsigned size)
{
    char b[200];
    snprintf(b, sizeof(b), "GPIOB %s off=0x%llx size=%u val=0x%llx\n",
             msg,
             (unsigned long long)rel_off,
             (unsigned)size,
             (unsigned long long)val);
    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", b);
}

// This function will emulate all device reads
static uint64_t gpiob_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc)
{
    (void)pc;
    gpiob_state_t *s = (gpiob_state_t *)opaque;
    hwaddr off = gpiob_norm_off(addr);

    switch ((uint32_t)off) {
        case GPIOB_MODER_OFF:
            return read_sized_u32(s->MODER, size, off);

        case GPIOB_OTYPER_OFF:
            return read_sized_u32(s->OTYPER, size, off);

        case GPIOB_OSPEEDR_OFF:
            return read_sized_u32(s->OSPEEDR, size, off);

        case GPIOB_PUPDR_OFF:
            return read_sized_u32(s->PUPDR, size, off);

        case GPIOB_ODR_OFF:
            return read_sized_u32(s->ODR, size, off);

        case GPIOB_BSRR_OFF:
            // Not expected to be read; return 0.
            return 0;

        default:
            // Unknown offset based on provided traces.
            // dbg(s, "READ unknown -> 0", off, 0, size);
            return 0;
    }
}

// This function will emulate all device writes
static void gpiob_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc)
{
    (void)pc;
    gpiob_state_t *s = (gpiob_state_t *)opaque;
    hwaddr off = gpiob_norm_off(addr);

    switch ((uint32_t)off) {
        case GPIOB_MODER_OFF:
            s->MODER = apply_partial_write32(s->MODER, off, value, size);
            break;

        case GPIOB_OTYPER_OFF:
            s->OTYPER = apply_partial_write32(s->OTYPER, off, value, size) & 0x0000FFFFu;
            break;

        case GPIOB_OSPEEDR_OFF:
            s->OSPEEDR = apply_partial_write32(s->OSPEEDR, off, value, size);
            break;

        case GPIOB_PUPDR_OFF:
            s->PUPDR = apply_partial_write32(s->PUPDR, off, value, size);
            break;

        case GPIOB_ODR_OFF:
            // Not observed as write in the provided traces, but implement safely.
            s->ODR = apply_partial_write32(s->ODR, off, value, size) & 0x0000FFFFu;
            break;

        case GPIOB_BSRR_OFF: {
            // Support partial writes too by placing the written bytes at the proper position
            // within the 32-bit BSRR word.
            //
            // BSRR layout (conceptual 32-bit):
            //   [15:0]   SET bits
            //   [31:16]  RESET bits
            //
            // This also naturally supports halfword writes to BSRR+2 behaving like reset-only.
            uint32_t m = mask_for_size(size);
            unsigned shift = (unsigned)((off & 0x3) * 8);
            uint32_t bsrr_word = ((uint32_t)value & m) << shift;

            uint32_t set_mask   = (bsrr_word & 0x0000FFFFu);
            uint32_t reset_mask = (bsrr_word >> 16) & 0x0000FFFFu;

            uint32_t odr = s->ODR & 0x0000FFFFu;
            odr |= set_mask;
            odr &= ~reset_mask;
            s->ODR = odr;

            break;
        }

        default:
            // dbg(s, "WRITE unknown (ignored)", off, value, size);
            break;
    }
}

static void *gpiob_init(const FdDevice *dev, const char *config_json, const FdHost *host)
{
    (void)config_json;
    gpiob_state_t *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->base = dev->ranges[0].base;
    s->host = host;
    s->name = dev->name;

    // Seed register values to match the *hardware* initial reads in init.txt.
    // This is critical for correct RMW behavior and to avoid the observed mismatch.
    s->OSPEEDR = 0x000000C0u;   // hardware read before write: 0xC0
    s->OTYPER  = 0x00000000u;   // hardware read: 0x0
    s->PUPDR   = 0x00000100u;   // hardware read: 0x100
    s->MODER   = 0xFFFFFEBFu;   // hardware read: 0xFFFFFEBF
    s->ODR     = 0x00000000u;   // observed reads: 0x0

    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "GPIOB init: seeded defaults + robust absolute/offset address decode.\n");
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = gpiob_init,
    .read = gpiob_read,
    .write = gpiob_write,
};
