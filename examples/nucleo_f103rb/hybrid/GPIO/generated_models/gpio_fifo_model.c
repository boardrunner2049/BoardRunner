// Device Model for GPIO (STM32F103xx) - GPIOA + GPIOC
//
// Observable / interactive behavior:
// - Exposes FIFO endpoints:
//     /tmp/gpioc_in   : host -> model (simulate PC13 button; 0=press/low, 1=release/high)
//     /tmp/gpioa_out  : model -> host (logs PA ODR changes; useful for LED observation)
//     /tmp/gpioc_out  : model -> host (logs PC ODR changes)
// - Periodic timer polls *_in FIFOs non-blocking and updates IDR accordingly.
//
// Notes:
// - Implements STM32F1-style CRL/CRH pin decode (MODE/CNF).
// - In input pull-up/pull-down mode (CNF=2, MODE=0), the default level follows ODR
//   unless an external override is active (from FIFO input).
// - For output pins, IDR reflects ODR (reasonable approximation absent external wiring).
//
// Build: includes <fastdyn/device_model.h> and <vio/vio.h>; boardrunner build-models gpio_fifo_model.c

#include <fastdyn/device_model.h>
#include <vio/vio.h>

#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#ifndef hwaddr
typedef uint64_t hwaddr; // fallback if not provided by headers
#endif

#define GPIOA_BASE 0x40010800u
#define GPIOC_BASE 0x40011000u

#define GPIO_CRL_OFF   0x00u
#define GPIO_CRH_OFF   0x04u
#define GPIO_IDR_OFF   0x08u
#define GPIO_ODR_OFF   0x0Cu
#define GPIO_BSRR_OFF  0x10u
#define GPIO_BRR_OFF   0x14u
#define GPIO_LCKR_OFF  0x18u

#define GPIO_PORT_MAGIC 0x4750494Fu  // 'GPIO'
#define GPIO_BANK_MAGIC 0x47424E4Bu  // 'GBNK'

#define GPIO_POLL_PERIOD_NS 1000000ull  // 1ms

struct GPIOBank;

typedef struct GPIOPortState {
    uint32_t magic;
    uint32_t base;       // absolute base
    char     name;       // 'A' or 'C'

    uint32_t crl;
    uint32_t crh;
    uint16_t idr_cached; // last computed
    uint16_t odr;
    uint32_t lckr;

    // External override (host-driven) for input pins:
    // ext_mask bit=1 means externally driven; ext_level gives level when driven.
    uint16_t ext_mask;
    uint16_t ext_level;

    // Host I/O
    int fifo_in_fd;
    int fifo_out_fd;
    char fifo_in_path[64];
    char fifo_out_path[64];

    uint64_t poll_timer;
    const struct GPIOBank *bank;   /* the instance this port belongs to */
} GPIOPortState;

typedef struct GPIOBank {
    uint32_t magic;
    GPIOPortState a;
    GPIOPortState c;
    bool initialized;
    uint64_t base;      /* the device's base address, from dev->ranges[0].base */
    const FdHost *host;
    const char *name;
} GPIOBank;


/* Log through the host of the instance the port belongs to. */
#define PORT_LOG(p, buf) (p)->bank->host->log(FD_LOG_LEVEL_DEBUG, (p)->bank->name, "%s", (buf))

static void dbg_u32(const GPIOPortState *p, const char *tag, uint32_t val) {
    char port = p->name;
    char buf[128];
    // Keep messages short but useful.
    snprintf(buf, sizeof(buf), "[gpio%c] %s=0x%08x\n", port, tag, (unsigned)val);
    PORT_LOG(p, buf);
}

static void dbg_u16(const GPIOPortState *p, const char *tag, uint16_t val) {
    char port = p->name;
    char buf[128];
    snprintf(buf, sizeof(buf), "[gpio%c] %s=0x%04x\n", port, tag, (unsigned)val);
    PORT_LOG(p, buf);
}

// Decode pin config nibble for STM32F1:
// nibble bits: [CNF1 CNF0 MODE1 MODE0]
static inline void gpio_get_pin_cfg(const GPIOPortState *p, int pin, uint8_t *mode, uint8_t *cnf) {
    uint32_t reg = (pin < 8) ? p->crl : p->crh;
    int shift = (pin & 7) * 4;
    uint8_t nib = (reg >> shift) & 0xFu;
    *mode = (uint8_t)(nib & 0x3u);
    *cnf  = (uint8_t)((nib >> 2) & 0x3u);
}

static inline bool gpio_is_input(uint8_t mode) {
    return mode == 0;
}

static uint16_t gpio_compute_idr(GPIOPortState *p) {
    uint16_t idr = 0;

    for (int pin = 0; pin < 16; pin++) {
        uint16_t bit = (uint16_t)(1u << pin);

        // External override wins.
        if (p->ext_mask & bit) {
            if (p->ext_level & bit) idr |= bit;
            continue;
        }

        uint8_t mode, cnf;
        gpio_get_pin_cfg(p, pin, &mode, &cnf);

        if (!gpio_is_input(mode)) {
            // Output mode: approximate pin state as ODR.
            if (p->odr & bit) idr |= bit;
            continue;
        }

        // Input mode:
        // CNF meanings in input mode:
        // 00: analog
        // 01: floating
        // 10: pull-up/pull-down (selected by ODR bit)
        // 11: reserved
        if (cnf == 2) {
            // Pull-up/pull-down selected by ODR bit
            if (p->odr & bit) idr |= bit; // pull-up => 1 when not driven
            else              idr &= (uint16_t)~bit; // pull-down => 0
        } else {
            // Floating/analog: default high to avoid spurious "pressed" unless driven.
            idr |= bit;
        }
    }

    p->idr_cached = idr;
    return idr;
}

static void gpio_write_out_log(GPIOPortState *p, uint16_t changed_mask) {
    if (p->fifo_out_fd < 0) return;

    char msg[160];
    int64_t t = qemu_plugin_get_virtual_timer();
    snprintf(msg, sizeof(msg),
             "t=%lldns gpio%c ODR=0x%04x changed=0x%04x\n",
             (long long)t, p->name, (unsigned)p->odr, (unsigned)changed_mask);

    (void)api_fifo_write(p->fifo_out_fd, msg, (int)strlen(msg));
}

static inline uint32_t gpio_addr_to_offset(uint32_t abs_addr, uint32_t base) {
    return abs_addr - base;
}

static GPIOPortState *gpio_port_from_access(void *opaque, hwaddr addr, uint32_t *out_off) {
    GPIOBank *b = (GPIOBank *)opaque;   /* the instance */
    // 1) If opaque is a GPIOPortState, use it (supports per-port instantiation where addr may be offset).
    if (opaque) {
        GPIOPortState *ptry = (GPIOPortState *)opaque;
        if (ptry->magic == GPIO_PORT_MAGIC && ptry->base != 0) {
            uint32_t a = (uint32_t)addr;
            uint32_t off = (a < 0x100u) ? a : gpio_addr_to_offset(a, ptry->base);
            *out_off = off;
            return ptry;
        }
        // 2) If opaque is a GPIOBank, use it.
        GPIOBank *btry = (GPIOBank *)opaque;
        if (btry->magic == GPIO_BANK_MAGIC) {
            // fallthrough to absolute mapping below using that bank
        }
    }

    // 3) Default: absolute mapping against known bases (works when QEMU passes absolute addresses).
    uint32_t a = (uint32_t)addr;

    if (a >= GPIOA_BASE && a < (GPIOA_BASE + 0x20u)) {
        *out_off = a - GPIOA_BASE;
        return &b->a;
    }
    if (a >= GPIOC_BASE && a < (GPIOC_BASE + 0x20u)) {
        *out_off = a - GPIOC_BASE;
        return &b->c;
    }

    // 4) If it looks like an offset access but opaque wasn't a port, assume GPIOA.
    if (a < 0x20u) {
        *out_off = a;
        return &b->a;
    }

    *out_off = 0;
    return NULL;
}

// FIFO input protocol:
// - If byte is 0x00 or 0x01: treated as "PC13 button" for GPIOC:
//     0x00 => press  (drive PC13 low)
//     0x01 => release(drive PC13 high)
// - If (byte & 0x80) != 0: generic pin event for that port:
//     pin   = byte & 0x0F
//     level = (byte >> 4) & 1
//     drive = (byte >> 5) & 1   (1=drive externally, 0=release to internal pull/default)
//   Example: drive pin 13 low: 0x80 | (1<<5) | (0<<4) | 13  = 0xAD
static void gpio_handle_input_byte(GPIOPortState *p, uint8_t b) {
    if (p->name == 'C' && (b == 0x00u || b == 0x01u)) {
        uint16_t bit = (uint16_t)(1u << 13);
        p->ext_mask |= bit;
        if (b == 0x01u) p->ext_level |= bit;   // release => high
        else            p->ext_level &= (uint16_t)~bit; // press => low

        char buf[128];
        snprintf(buf, sizeof(buf), "[gpioC] host button PC13 -> %s\n",
                 (b == 0x00u) ? "PRESSED (low)" : "RELEASED (high)");
        PORT_LOG(p, buf);
        return;
    }

    if (b & 0x80u) {
        int pin = (int)(b & 0x0Fu);
        int level = (int)((b >> 4) & 1u);
        int drive = (int)((b >> 5) & 1u);
        if (pin < 0 || pin > 15) return;

        uint16_t bit = (uint16_t)(1u << pin);
        if (drive) {
            p->ext_mask |= bit;
            if (level) p->ext_level |= bit;
            else       p->ext_level &= (uint16_t)~bit;
        } else {
            p->ext_mask &= (uint16_t)~bit; // release
        }

        char buf[160];
        snprintf(buf, sizeof(buf),
                 "[gpio%c] host pin%d %s %s\n",
                 p->name, pin, drive ? "DRIVE" : "RELEASE", level ? "HIGH" : "LOW");
        PORT_LOG(p, buf);
    }
}

static void gpio_poll_fifo_cb(void *data) {
    GPIOPortState *p = (GPIOPortState *)data;
    if (!p || p->magic != GPIO_PORT_MAGIC) return;
    if (p->fifo_in_fd < 0) return;

    uint8_t b;
    // Drain all available bytes.
    while (api_fifo_read_nonblock(p->fifo_in_fd, &b) == 1) {
        gpio_handle_input_byte(p, b);
    }
}

// Device Model for GPIO

// This function will emulate all device reads
static uint64_t gpio_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc) {
    (void)pc;
    GPIOBank *s = (GPIOBank *)opaque;
    uint32_t off = 0;
    GPIOPortState *p = gpio_port_from_access(opaque, addr, &off);
    if (!p) {
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "[gpio] read to unknown address\n");
        return 0;
    }

    uint32_t val32 = 0;

    switch (off) {
    case GPIO_CRL_OFF:
        val32 = p->crl;
        break;
    case GPIO_CRH_OFF:
        val32 = p->crh;
        break;
    case GPIO_IDR_OFF: {
        uint16_t idr = gpio_compute_idr(p);
        val32 = (uint32_t)idr; // lower 16 bits
        break;
    }
    case GPIO_ODR_OFF:
        val32 = (uint32_t)p->odr;
        break;
    case GPIO_BSRR_OFF:
        // Not a real readable register in many uses; return 0 for safety.
        val32 = 0;
        break;
    case GPIO_BRR_OFF:
        val32 = 0;
        break;
    case GPIO_LCKR_OFF:
        val32 = p->lckr;
        break;
    default:
        // For unmapped offsets, be conservative.
        val32 = 0;
        break;
    }

    // Respect access size (best-effort).
    if (size == 1) return (uint8_t)(val32 & 0xFFu);
    if (size == 2) return (uint16_t)(val32 & 0xFFFFu);
    return (uint64_t)val32;
}

// This function will emulate all device writes
static void gpio_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc) {
    (void)pc;
    GPIOBank *s = (GPIOBank *)opaque;
    uint32_t off = 0;
    GPIOPortState *p = gpio_port_from_access(opaque, addr, &off);
    if (!p) {
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "[gpio] write to unknown address\n");
        return;
    }

    // Mask incoming value by size
    uint32_t v = (uint32_t)value;
    if (size == 1) v &= 0xFFu;
    else if (size == 2) v &= 0xFFFFu;

    switch (off) {
    case GPIO_CRL_OFF:
        p->crl = v;
        dbg_u32(p, "CRL", p->crl);
        break;

    case GPIO_CRH_OFF:
        p->crh = v;
        dbg_u32(p, "CRH", p->crh);
        break;

    case GPIO_ODR_OFF: {
        uint16_t new_odr = (uint16_t)(v & 0xFFFFu);
        uint16_t changed = (uint16_t)(p->odr ^ new_odr);
        p->odr = new_odr;
        if (changed) {
            dbg_u16(p, "ODR", p->odr);
            gpio_write_out_log(p, changed);
        }
        break;
    }

    case GPIO_BSRR_OFF: {
        // Lower 16 bits set, upper 16 bits reset.
        uint16_t set_mask   = (uint16_t)(v & 0xFFFFu);
        uint16_t reset_mask = (uint16_t)((v >> 16) & 0xFFFFu);

        uint16_t old = p->odr;
        uint16_t newv = (uint16_t)((old | set_mask) & (uint16_t)~reset_mask);
        uint16_t changed = (uint16_t)(old ^ newv);
        p->odr = newv;

        // Debug: useful for observing LED patterns in trace-like style.
        char buf[160];
        snprintf(buf, sizeof(buf),
                 "[gpio%c] BSRR write=0x%08x set=0x%04x reset=0x%04x ODR:0x%04x->0x%04x\n",
                 p->name, (unsigned)v, (unsigned)set_mask, (unsigned)reset_mask,
                 (unsigned)old, (unsigned)newv);
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", buf);

        if (changed) gpio_write_out_log(p, changed);
        break;
    }

    case GPIO_BRR_OFF: {
        // Reset bits directly.
        uint16_t reset_mask = (uint16_t)(v & 0xFFFFu);
        uint16_t old = p->odr;
        uint16_t newv = (uint16_t)(old & (uint16_t)~reset_mask);
        uint16_t changed = (uint16_t)(old ^ newv);
        p->odr = newv;

        char buf[140];
        snprintf(buf, sizeof(buf),
                 "[gpio%c] BRR write=0x%04x ODR:0x%04x->0x%04x\n",
                 p->name, (unsigned)reset_mask, (unsigned)old, (unsigned)newv);
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", buf);

        if (changed) gpio_write_out_log(p, changed);
        break;
    }

    case GPIO_LCKR_OFF:
        p->lckr = v;
        dbg_u32(p, "LCKR", p->lckr);
        break;

    default:
        // Unknown offset: ignore but log (helps reverse engineering).
        s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "[gpio] write to unknown offset\n");
        break;
    }
}

static void gpio_port_init(GPIOPortState *p, const struct GPIOBank *bank, char name, uint32_t base,
                           const char *fifo_in, const char *fifo_out) {
    memset(p, 0, sizeof(*p));
    p->bank = bank;
    p->magic = GPIO_PORT_MAGIC;
    p->name = name;
    p->base = base;

    // Reset-like defaults that match observed initial reads.
    p->crl = 0x44444444u;
    p->crh = 0x44444444u;
    p->odr = 0x0000u;
    p->lckr = 0x00000000u;

    // Default inputs high (safe for "button not pressed").
    p->ext_mask = 0;
    p->ext_level = 0xFFFFu;

    snprintf(p->fifo_in_path, sizeof(p->fifo_in_path), "%s", fifo_in);
    snprintf(p->fifo_out_path, sizeof(p->fifo_out_path), "%s", fifo_out);

    p->fifo_in_fd = api_fifo_open(p->fifo_in_path);
    p->fifo_out_fd = api_fifo_open(p->fifo_out_path);

    // Start periodic poll timer for interactivity.
    p->poll_timer = qemu_plugin_timer_new_period_ns(gpio_poll_fifo_cb, p, GPIO_POLL_PERIOD_NS);

    char buf[200];
    snprintf(buf, sizeof(buf),
             "[gpio%c] init base=0x%08x fifo_in=%s fifo_out=%s poll=%lluns\n",
             p->name, (unsigned)p->base, p->fifo_in_path, p->fifo_out_path,
             (unsigned long long)GPIO_POLL_PERIOD_NS);
    PORT_LOG(p, buf);
}

static void *gpio_init(const FdDevice *dev, const char *config_json, const FdHost *host) {
    (void)config_json;

    GPIOBank *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->base = dev->ranges[0].base;
    s->host = host;
    s->name = dev->name;
    s->magic = GPIO_BANK_MAGIC;
    s->initialized = true;

    gpio_port_init(&s->a, s, 'A', GPIOA_BASE, "/tmp/gpioa_in", "/tmp/gpioa_out");
    gpio_port_init(&s->c, s, 'C', GPIOC_BASE, "/tmp/gpioc_in", "/tmp/gpioc_out");

    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "[gpio] bank init complete (GPIOA + GPIOC)\n");
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = gpio_init,
    .read = gpio_read,
    .write = gpio_write,
};
