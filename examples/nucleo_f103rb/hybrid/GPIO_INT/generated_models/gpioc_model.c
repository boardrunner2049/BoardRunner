// Device Model for GPIOC (STM32F103xx)
//
// Based ONLY on provided traces:
//  - CRH reads default 0x44444444, then written to 0x44844444
//  - BSRR written with 0x2000 (set bit 13)
//  - IDR polled returning 0xFFFF then 0xDFFF (bit 13 low)
//
// Implemented behavior:
//  - Maintain CRL/CRH/ODR/LCKR state.
//  - BSRR updates ODR using STM32F1 semantics (set lower 16, reset upper 16).
//  - IDR returns mostly 1s, with bit 13 alternating high/low on successive reads
//    to reproduce the observed loop pattern (0xFFFF then 0xDFFF).
//
// Notes:
//  - No IRQ behavior implemented (none observed).
//  - Unobserved registers return stored/default values or 0 with debug logs.

#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

#include <fastdyn/device_model.h>

#define GPIOC_BASE_ADDR   0x40011000ULL

// Register offsets (STM32F1 GPIO block)
#define GPIOx_CRL_OFF     0x00
#define GPIOx_CRH_OFF     0x04
#define GPIOx_IDR_OFF     0x08
#define GPIOx_ODR_OFF     0x0C
#define GPIOx_BSRR_OFF    0x10
#define GPIOx_BRR_OFF     0x14
#define GPIOx_LCKR_OFF    0x18

typedef struct gpioc_state {
    uint32_t crl;     // config pins 0..7
    uint32_t crh;     // config pins 8..15
    uint32_t odr;     // output data / pull selector for input PU/PD
    uint32_t lckr;    // lock
    uint64_t idr_reads;
    uint64_t base;      /* the device's base address, from dev->ranges[0].base */
    const FdHost *host;
    const char *name;
} gpioc_state_t;


static void gpioc_logf(gpioc_state_t *s, const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", buf);
}

static inline uint32_t gpioc_norm_off(hwaddr addr)
{
    // Be robust: some frameworks pass absolute addresses, others pass region offsets.
    if ((uint64_t)addr >= GPIOC_BASE_ADDR) {
        return (uint32_t)((uint64_t)addr - GPIOC_BASE_ADDR);
    }
    return (uint32_t)addr;
}

static inline uint8_t gpioc_crh_nibble_for_pin(gpioc_state_t *s, int pin)
{
    // pin 8..15 => CRH nibble index 0..7
    int idx = pin - 8;
    return (uint8_t)((s->crh >> (idx * 4)) & 0xF);
}

static uint16_t gpioc_compute_idr(gpioc_state_t *s)
{
    // Observed values are 0xFFFF and 0xDFFF, i.e., "everything high" except
    // bit 13 occasionally low. We'll model that directly and deterministically.
    uint16_t v = 0xFFFF;

    // Base level for PC13 if in input pull-up/down mode on STM32F1:
    // the corresponding ODR bit selects PU (1) or PD (0).
    // We only infer this because BSRR=0x2000 happens and then IDR is polled.
    uint16_t pc13_base = 1;

    uint8_t n13 = gpioc_crh_nibble_for_pin(s, 13);

    // Heuristic limited to what we saw:
    // nibble 0x8 appears in trace (CRH becomes 0x44844444 => pin13 nibble = 0x8).
    // Treat 0x8 as "input pull-up/down" so ODR bit selects pull direction.
    if (n13 == 0x8) {
        pc13_base = (uint16_t)((s->odr >> 13) & 0x1);
    } else {
        // Otherwise, default to reading high unless firmware drives it via ODR.
        pc13_base = (uint16_t)((s->odr >> 13) & 0x1);
        if (pc13_base == 0) pc13_base = 1;
    }

    // Deterministic "virtual input event" to reproduce loop pattern:
    // first IDR read => high (0xFFFF), second => low on bit13 (0xDFFF), repeat.
    bool pressed = ((s->idr_reads & 0x1ULL) == 0x1ULL);

    if (pressed) {
        v &= (uint16_t)~(1u << 13);      // force low on PC13
    } else {
        if (pc13_base) v |= (1u << 13);  // high
        else           v &= (uint16_t)~(1u << 13); // low (pull-down case)
    }

    return v;
}

// This function will emulate all device reads
static uint64_t gpioc_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc)
{
    (void)pc;
    gpioc_state_t *s = (gpioc_state_t *)opaque;

    uint32_t off = gpioc_norm_off(addr);
    uint32_t val32 = 0;

    switch (off) {
    case GPIOx_CRL_OFF:
        val32 = s->crl;
        break;
    case GPIOx_CRH_OFF:
        val32 = s->crh;
        break;
    case GPIOx_ODR_OFF:
        val32 = s->odr;
        break;
    case GPIOx_LCKR_OFF:
        val32 = s->lckr;
        break;
    case GPIOx_IDR_OFF: {
        uint16_t idr = gpioc_compute_idr(s);
        s->idr_reads++;
        val32 = (uint32_t)idr;
        break;
    }
    default:
        gpioc_logf(s, "[GPIOC] READ unknown off=0x%02X size=%u (addr=0x%llX)\n",
                   off, size, (unsigned long long)addr);
        val32 = 0;
        break;
    }

    // Honor access size (1/2/4) by masking. Traces show 4-byte reads.
    if (size == 1) return (uint8_t)(val32 & 0xFF);
    if (size == 2) return (uint16_t)(val32 & 0xFFFF);
    return (uint32_t)val32;
}

// This function will emulate all device writes
static void gpioc_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc)
{
    (void)pc;
    gpioc_state_t *s = (gpioc_state_t *)opaque;

    uint32_t off = gpioc_norm_off(addr);

    // Normalize write value to 32-bit based on size
    uint32_t v32;
    if (size == 1) v32 = (uint32_t)((uint8_t)value);
    else if (size == 2) v32 = (uint32_t)((uint16_t)value);
    else v32 = (uint32_t)value;

    switch (off) {
    case GPIOx_CRL_OFF:
        s->crl = v32;
        gpioc_logf(s, "[GPIOC] WRITE CRL=0x%08X\n", s->crl);
        break;

    case GPIOx_CRH_OFF:
        s->crh = v32;
        gpioc_logf(s, "[GPIOC] WRITE CRH=0x%08X\n", s->crh);
        break;

    case GPIOx_ODR_OFF:
        s->odr = v32 & 0xFFFF; // only 16 pins
        gpioc_logf(s, "[GPIOC] WRITE ODR=0x%04X\n", (unsigned)(s->odr & 0xFFFF));
        break;

    case GPIOx_BSRR_OFF: {
        // STM32F1: lower 16 bits set ODR bits; upper 16 bits reset ODR bits.
        uint16_t set_mask   = (uint16_t)(v32 & 0xFFFF);
        uint16_t reset_mask = (uint16_t)((v32 >> 16) & 0xFFFF);

        uint16_t odr16 = (uint16_t)(s->odr & 0xFFFF);
        odr16 |= set_mask;
        odr16 &= (uint16_t)~reset_mask;
        s->odr = (uint32_t)odr16;

        gpioc_logf(s, "[GPIOC] WRITE BSRR=0x%08X => ODR=0x%04X\n",
                   v32, (unsigned)(s->odr & 0xFFFF));
        break;
    }

    case GPIOx_BRR_OFF: {
        // BRR resets bits (lower 16)
        uint16_t reset_mask = (uint16_t)(v32 & 0xFFFF);
        uint16_t odr16 = (uint16_t)(s->odr & 0xFFFF);
        odr16 &= (uint16_t)~reset_mask;
        s->odr = (uint32_t)odr16;

        gpioc_logf(s, "[GPIOC] WRITE BRR=0x%04X => ODR=0x%04X\n",
                   (unsigned)reset_mask, (unsigned)(s->odr & 0xFFFF));
        break;
    }

    case GPIOx_LCKR_OFF:
        s->lckr = v32;
        gpioc_logf(s, "[GPIOC] WRITE LCKR=0x%08X\n", s->lckr);
        break;

    default:
        gpioc_logf(s, "[GPIOC] WRITE unknown off=0x%02X size=%u value=0x%08X (addr=0x%llX)\n",
                   off, size, v32, (unsigned long long)addr);
        break;
    }
}

static void *gpioc_init(const FdDevice *dev, const char *config_json, const FdHost *host)
{
    (void)config_json;
    gpioc_state_t *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->base = dev->ranges[0].base;
    s->host = host;
    s->name = dev->name;

    // Match observed reset/default read:
    // CRH read returns 0x44444444 before firmware writes 0x44844444.
    s->crl = 0x44444444;
    s->crh = 0x44444444;

    // ODR defaults 0. Firmware writes BSRR=0x2000 (sets bit13) during init.
    s->odr = 0x0000;

    s->lckr = 0;
    s->idr_reads = 0;

    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "[GPIOC] init: CRL/CRH=0x44444444, ODR=0x0000\n");
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = gpioc_init,
    .read = gpioc_read,
    .write = gpioc_write,
};
