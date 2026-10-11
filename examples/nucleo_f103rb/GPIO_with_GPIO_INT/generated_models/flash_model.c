// Device Model for FLASH

#include <fastdyn/device_model.h>

#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

// Inferred Register Functions:
// - ACR   (0x00): Access control register. Firmware changes latency from 0x30 to 0x32.
//                  PRFTBS is treated as read-only status mirroring PRFTBE.
// - KEYR  (0x04): FLASH key register (minimal unlock support).
// - OPTKEYR (0x08): Option byte key register (minimal state only).
// - SR    (0x0C): Status register, minimal W1C flag behavior.
// - CR    (0x10): Control register, minimal lock semantics.
// - AR    (0x14): Address register, simple storage.
// - OBR   (0x1C): Option byte register, read-only stored value.
// - WRPR  (0x20): Write protection register, read-only stored value.
//
// Note: No flash array programming/erase is implemented because the trace only shows
//       ACR accesses and the provided memory APIs are RAM-oriented.

#define FLASH_BASE_ADDR      0x40022000ULL

#define FLASH_ACR_OFFSET     0x00
#define FLASH_KEYR_OFFSET    0x04
#define FLASH_OPTKEYR_OFFSET 0x08
#define FLASH_SR_OFFSET      0x0C
#define FLASH_CR_OFFSET      0x10
#define FLASH_AR_OFFSET      0x14
#define FLASH_OBR_OFFSET     0x1C
#define FLASH_WRPR_OFFSET    0x20

// ACR bits
#define FLASH_ACR_LATENCY_MASK  0x00000007u
#define FLASH_ACR_HLFCYA        0x00000008u
#define FLASH_ACR_PRFTBE        0x00000010u
#define FLASH_ACR_PRFTBS        0x00000020u
#define FLASH_ACR_WRITABLE_MASK (FLASH_ACR_LATENCY_MASK | FLASH_ACR_HLFCYA | FLASH_ACR_PRFTBE)

// SR bits
#define FLASH_SR_BSY            0x00000001u
#define FLASH_SR_PGERR          0x00000004u
#define FLASH_SR_WRPRTERR       0x00000010u
#define FLASH_SR_EOP            0x00000020u
#define FLASH_SR_VALID_MASK     (FLASH_SR_BSY | FLASH_SR_PGERR | FLASH_SR_WRPRTERR | FLASH_SR_EOP)
#define FLASH_SR_W1C_MASK       (FLASH_SR_PGERR | FLASH_SR_WRPRTERR | FLASH_SR_EOP)

// CR bits
#define FLASH_CR_PG             0x00000001u
#define FLASH_CR_PER            0x00000002u
#define FLASH_CR_MER            0x00000004u
#define FLASH_CR_OPTPG          0x00000010u
#define FLASH_CR_OPTER          0x00000020u
#define FLASH_CR_STRT           0x00000040u
#define FLASH_CR_LOCK           0x00000080u
#define FLASH_CR_OPTWRE         0x00000200u
#define FLASH_CR_ERRIE          0x00000400u
#define FLASH_CR_EOPIE          0x00001000u
#define FLASH_CR_OBL_LAUNCH     0x00002000u
#define FLASH_CR_VALID_MASK     (FLASH_CR_PG | FLASH_CR_PER | FLASH_CR_MER | \
                                 FLASH_CR_OPTPG | FLASH_CR_OPTER | FLASH_CR_STRT | \
                                 FLASH_CR_LOCK | FLASH_CR_OPTWRE | FLASH_CR_ERRIE | \
                                 FLASH_CR_EOPIE | FLASH_CR_OBL_LAUNCH)

// FLASH key values
#define FLASH_KEY1              0x45670123u
#define FLASH_KEY2              0xCDEF89ABu

typedef struct {
    uint32_t acr;          // stores writable ACR bits only; PRFTBS is synthesized on read
    uint32_t sr;
    uint32_t cr;
    uint32_t ar;
    uint32_t obr;
    uint32_t wrpr;

    uint32_t last_keyr;
    uint32_t last_optkeyr;
    uint8_t keyr_stage;
    uint8_t optkeyr_stage;
    bool opt_unlocked;
    uint64_t base;      /* the device's base address, from dev->ranges[0].base */
    const FdHost *host;
    const char *name;
} FLASHState;


static void flash_debug(const FLASHState *s, const char *fmt, uint64_t a, uint64_t b, uint64_t c)
{
    char buf[160];
    snprintf(buf, sizeof(buf), fmt, (unsigned long long)a, (unsigned long long)b,
             (unsigned long long)c);
    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", buf);
}

static bool flash_access_crosses_reg(hwaddr offset, unsigned size)
{
    return (((unsigned)(offset & 0x3u)) + size) > 4;
}

static uint32_t flash_extract_u32(uint32_t reg, hwaddr offset, unsigned size)
{
    unsigned shift = (unsigned)(offset & 0x3u) * 8u;

    if (size >= 4) {
        return reg;
    } else if (size == 2) {
        return (reg >> shift) & 0xFFFFu;
    } else if (size == 1) {
        return (reg >> shift) & 0xFFu;
    }

    return 0;
}

static uint32_t flash_merge_u32(uint32_t oldv, uint64_t value, hwaddr offset, unsigned size)
{
    unsigned shift = (unsigned)(offset & 0x3u) * 8u;
    uint32_t mask;

    if (size >= 4) {
        return (uint32_t)value;
    } else if (size == 2) {
        mask = 0xFFFFu << shift;
    } else if (size == 1) {
        mask = 0xFFu << shift;
    } else {
        return oldv;
    }

    return (oldv & ~mask) | (((uint32_t)value << shift) & mask);
}

static uint32_t flash_acr_readback(FLASHState *s)
{
    uint32_t v = s->acr & FLASH_ACR_WRITABLE_MASK;

    // PRFTBS is hardware-owned read-only status; for this minimal model it mirrors PRFTBE.
    if (v & FLASH_ACR_PRFTBE) {
        v |= FLASH_ACR_PRFTBS;
    } else {
        v &= ~FLASH_ACR_PRFTBS;
    }

    return v;
}

static uint32_t flash_read_reg32(FLASHState *s, hwaddr reg_off)
{
    switch (reg_off) {
    case FLASH_ACR_OFFSET:
        return flash_acr_readback(s);

    case FLASH_KEYR_OFFSET:
        return 0; // write-only in practice; return 0 conservatively

    case FLASH_OPTKEYR_OFFSET:
        return 0; // write-only in practice; return 0 conservatively

    case FLASH_SR_OFFSET:
        return s->sr & FLASH_SR_VALID_MASK;

    case FLASH_CR_OFFSET:
        return s->cr & FLASH_CR_VALID_MASK;

    case FLASH_AR_OFFSET:
        return s->ar;

    case FLASH_OBR_OFFSET:
        return s->obr;

    case FLASH_WRPR_OFFSET:
        return s->wrpr;

    default:
        flash_debug(s, "FLASH: unhandled read reg_off=0x%llx", reg_off, 0, 0);
        return 0;
    }
}

static void flash_handle_keyr_write(FLASHState *s, uint32_t value)
{
    s->last_keyr = value;

    if (s->keyr_stage == 0 && value == FLASH_KEY1) {
        s->keyr_stage = 1;
    } else if (s->keyr_stage == 1 && value == FLASH_KEY2) {
        s->cr &= ~FLASH_CR_LOCK;
        s->keyr_stage = 0;
    } else {
        s->keyr_stage = 0;
    }
}

static void flash_handle_optkeyr_write(FLASHState *s, uint32_t value)
{
    s->last_optkeyr = value;

    if (s->optkeyr_stage == 0 && value == FLASH_KEY1) {
        s->optkeyr_stage = 1;
    } else if (s->optkeyr_stage == 1 && value == FLASH_KEY2) {
        s->opt_unlocked = true;
        s->optkeyr_stage = 0;
    } else {
        s->optkeyr_stage = 0;
    }
}

static void flash_write_reg32(FLASHState *s, hwaddr reg_off, uint32_t value)
{
    switch (reg_off) {
    case FLASH_ACR_OFFSET:
        // Only LATENCY, HLFCYA, PRFTBE are writable. PRFTBS is read-only status.
        s->acr = value & FLASH_ACR_WRITABLE_MASK;
        break;

    case FLASH_KEYR_OFFSET:
        flash_handle_keyr_write(s, value);
        break;

    case FLASH_OPTKEYR_OFFSET:
        flash_handle_optkeyr_write(s, value);
        break;

    case FLASH_SR_OFFSET:
        // W1C for EOP/PGERR/WRPRTERR. BSY is read-only and remains 0 in this model.
        s->sr &= ~(value & FLASH_SR_W1C_MASK);
        break;

    case FLASH_CR_OFFSET: {
        uint32_t newv = value & FLASH_CR_VALID_MASK;

        if (s->cr & FLASH_CR_LOCK) {
            // When locked, FLASH_CR writes are ignored in hardware.
            // Preserve the locked state.
            s->cr |= FLASH_CR_LOCK;
            break;
        }

        // Option-byte write enable should not become visible unless option area was unlocked.
        if (!s->opt_unlocked) {
            newv &= ~FLASH_CR_OPTWRE;
        }

        s->cr = newv;

        // STRT / OBL_LAUNCH are pulse-like control bits; do not keep them set.
        s->cr &= ~(FLASH_CR_STRT | FLASH_CR_OBL_LAUNCH);

        // If software sets LOCK again, re-lock the interface.
        if (newv & FLASH_CR_LOCK) {
            s->cr |= FLASH_CR_LOCK;
            s->keyr_stage = 0;
        }
        break;
    }

    case FLASH_AR_OFFSET:
        // Address register is only meaningfully writable when unlocked.
        if (!(s->cr & FLASH_CR_LOCK)) {
            s->ar = value;
        }
        break;

    case FLASH_OBR_OFFSET:
        // Read-only register; ignore writes.
        break;

    case FLASH_WRPR_OFFSET:
        // Read-only register; ignore writes.
        break;

    default:
        flash_debug(s, "FLASH: unhandled write reg_off=0x%llx val=0x%llx",
                    reg_off, value, 0);
        break;
    }
}

// This function will emulate all device reads
static uint64_t flash_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc)
{
    (void)pc;
    FLASHState *s = (FLASHState *)opaque;
    hwaddr offset;
    hwaddr reg_off;
    uint32_t regv;


    if (addr < FLASH_BASE_ADDR) {
        flash_debug(s, "FLASH: read below base addr=0x%llx size=%llu", addr, size, 0);
        return 0;
    }

    offset = addr - FLASH_BASE_ADDR;

    if (size != 1 && size != 2 && size != 4) {
        flash_debug(s, "FLASH: unsupported read size addr=0x%llx size=%llu", addr, size, 0);
        return 0;
    }

    if (flash_access_crosses_reg(offset, size)) {
        flash_debug(s, "FLASH: cross-register read addr=0x%llx size=%llu", addr, size, 0);
        return 0;
    }

    reg_off = offset & ~0x3ULL;
    regv = flash_read_reg32(s, reg_off);
    return flash_extract_u32(regv, offset, size);
}

// This function will emulate all device writes
static void flash_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc)
{
    (void)pc;
    FLASHState *s = (FLASHState *)opaque;
    hwaddr offset;
    hwaddr reg_off;
    uint32_t oldv, newv;


    if (addr < FLASH_BASE_ADDR) {
        flash_debug(s, "FLASH: write below base addr=0x%llx val=0x%llx", addr, value, 0);
        return;
    }

    offset = addr - FLASH_BASE_ADDR;

    if (size != 1 && size != 2 && size != 4) {
        flash_debug(s, "FLASH: unsupported write size addr=0x%llx size=%llu", addr, size, 0);
        return;
    }

    if (flash_access_crosses_reg(offset, size)) {
        flash_debug(s, "FLASH: cross-register write addr=0x%llx size=%llu", addr, size, 0);
        return;
    }

    reg_off = offset & ~0x3ULL;
    oldv = flash_read_reg32(s, reg_off);
    newv = flash_merge_u32(oldv, value, offset, size);
    flash_write_reg32(s, reg_off, newv);
}

// MUST return pointer to state — framework passes it as opaque to _read/_write
static void *flash_init(const FdDevice *dev, const char *config_json, const FdHost *host)
{
    (void)config_json;
    FLASHState *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->base = dev->ranges[0].base;
    s->host = host;
    s->name = dev->name;

    // Trace-backed reset behavior:
    // Initial ACR read is 0x30, which corresponds to:
    // - PRFTBE = 1
    // - PRFTBS = 1 (read-only status synthesized from PRFTBE)
    // - LATENCY = 0
    s->acr = FLASH_ACR_PRFTBE;

    // Conservative reset state for the rest of the controller.
    s->sr = 0;
    s->cr = FLASH_CR_LOCK;   // STM32F1 FLASH control starts locked
    s->ar = 0;
    s->obr = 0;
    s->wrpr = 0;

    s->last_keyr = 0;
    s->last_optkeyr = 0;
    s->keyr_stage = 0;
    s->optkeyr_stage = 0;
    s->opt_unlocked = false;

    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = flash_init,
    .read = flash_read,
    .write = flash_write,
};
