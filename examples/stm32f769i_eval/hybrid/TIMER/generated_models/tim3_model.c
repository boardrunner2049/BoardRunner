// Device Model for TIM3 (STM32F7x9) — trace-driven, periodic update IRQ
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include <fastdyn/device_model.h>
#include <stdlib.h>
#include <vio/vio.h>

// -----------------------------------------------------------------------------
// TIM3 register map (offsets match the provided MMIO addresses)
// -----------------------------------------------------------------------------
#define TIM3_BASE_ADDR      0x40000400ULL

#define TIM3_CR1_OFF        0x00
#define TIM3_DIER_OFF       0x0C
#define TIM3_SR_OFF         0x10
#define TIM3_EGR_OFF        0x14
#define TIM3_CNT_OFF        0x24
#define TIM3_PSC_OFF        0x28
#define TIM3_ARR_OFF        0x2C

// Bits we care about
#define TIM_CR1_CEN         (1u << 0)   // Counter enable
#define TIM_CR1_UDIS        (1u << 1)   // Update disable
#define TIM_CR1_URS         (1u << 2)   // Update request source

#define TIM_DIER_UIE        (1u << 0)   // Update interrupt enable
#define TIM_SR_UIF          (1u << 0)   // Update interrupt flag

#define TIM_EGR_UG          (1u << 0)   // Update generation

// Observed SR reads are mostly 0x1E or 0x1F.
// We model bits[4:1] as a fixed "always-1" baseline and bit0 as UIF.
#define TIM3_SR_FIXED_MASK  0x0000001Eu

// TIM3 interrupt in traces: Vector=29. Required rule: raise_irq(vector + 16, false).
#define TIM3_VECTOR_NUM     29
#define TIM3_RAISE_LINE()   qemu_plugin_raise_irq((TIM3_VECTOR_NUM + 16), false)

// Assumption consistent with F7 typical clocks and your ARR/PSC producing ~1s:
// APB1 = 54MHz, TIM clocks = 2*APB1 = 108MHz.
#define TIM3_INPUT_HZ       108000000ULL

typedef struct tim3_state {
    // registers
    uint32_t cr1;
    uint32_t dier;
    uint32_t sr_var;      // we only vary UIF here; fixed mask is OR'ed on reads
    uint32_t cnt_shadow;  // latched counter when disabled / when we reset epoch
    uint32_t psc;
    uint32_t arr;

    // time base for CNT emulation
    uint64_t cnt_epoch_ns;     // virtual time when cnt_shadow was latched
    uint64_t update_timer_fd;  // one-shot timer handle
    uint64_t base;
    const FdHost *host;
    const char *name;
} tim3_state_t;

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------
static inline uint64_t vtime_now_ns(void) {
    int64_t t = qemu_plugin_get_virtual_timer();
    return (t < 0) ? 0ULL : (uint64_t)t;
}

static inline bool tim3_enabled(const tim3_state_t *s) {
    return (s->cr1 & TIM_CR1_CEN) != 0;
}

static inline uint64_t tim3_tick_ns(const tim3_state_t *s) {
    // tick = (psc+1)/TIM3_INPUT_HZ seconds
    uint64_t pscp1 = (uint64_t)s->psc + 1ULL;

    // Rounded-up integer division to avoid 0ns ticks.
    __uint128_t num = (__uint128_t)1000000000ULL * (__uint128_t)pscp1;
    uint64_t tick = (uint64_t)((num + (TIM3_INPUT_HZ - 1ULL)) / TIM3_INPUT_HZ);
    return (tick == 0ULL) ? 1ULL : tick;
}

static inline uint32_t tim3_arrp1_u32(const tim3_state_t *s) {
    // ARR is effectively 16-bit on TIM3, but we keep 32-bit; avoid arr+1 overflow.
    uint32_t a = s->arr;
    uint32_t ap1 = a + 1u;
    return (ap1 == 0u) ? 0xFFFFFFFFu : ap1; // extremely defensive
}

static uint32_t tim3_compute_cnt(const tim3_state_t *s, uint64_t now_ns) {
    uint32_t ap1 = tim3_arrp1_u32(s);
    if (!tim3_enabled(s) || ap1 == 0u) {
        return s->cnt_shadow;
    }

    uint64_t tick = tim3_tick_ns(s);
    uint64_t elapsed_ns = (now_ns >= s->cnt_epoch_ns) ? (now_ns - s->cnt_epoch_ns) : 0ULL;
    uint64_t elapsed_ticks = elapsed_ns / tick;

    uint64_t cnt = (uint64_t)s->cnt_shadow + elapsed_ticks;
    cnt %= (uint64_t)ap1;
    return (uint32_t)cnt;
}

static void tim3_latch_cnt(tim3_state_t *s, uint64_t now_ns) {
    s->cnt_shadow = tim3_compute_cnt(s, now_ns);
    s->cnt_epoch_ns = now_ns;
}

static void tim3_set_uif_and_irq(tim3_state_t *s) {
    // If UDIS=1, update events are disabled (no UIF / no interrupt).
    if (s->cr1 & TIM_CR1_UDIS) {
        return;
    }

    s->sr_var |= TIM_SR_UIF;

    if ((s->dier & TIM_DIER_UIE) && tim3_enabled(s)) {
        TIM3_RAISE_LINE();
    }
}

static void tim3_schedule_next_update(tim3_state_t *s, uint64_t now_ns) {
    if (!tim3_enabled(s)) {
        return;
    }

    uint32_t ap1 = tim3_arrp1_u32(s);
    if (ap1 == 0u) {
        return;
    }

    // Align epoch to "now" with current CNT to keep CNT monotonic across reschedules.
    uint32_t cnt_now = tim3_compute_cnt(s, now_ns);
    s->cnt_shadow = cnt_now;
    s->cnt_epoch_ns = now_ns;

    uint64_t tick = tim3_tick_ns(s);

    // Remaining ticks until update event when counting up 0..ARR:
    // If CNT == x, next overflow/update after (ARR - x + 1) ticks.
    uint32_t arr = s->arr;
    uint64_t remaining_ticks = (uint64_t)((arr >= cnt_now) ? (arr - cnt_now + 1u) : (arr + 1u));

    uint64_t delay_ns = remaining_ticks * tick;
    if (delay_ns == 0ULL) {
        delay_ns = tick;
    }

    // API expects absolute timestamp.
    qemu_plugin_timer_alarm(s->update_timer_fd, now_ns + delay_ns);
}

static void tim3_update_cb(void *opaque) {
    tim3_state_t *s = (tim3_state_t *)opaque;
    uint64_t now = vtime_now_ns();

    if (!tim3_enabled(s)) {
        // Timer was disabled after arming; do nothing and do not reschedule.
        return;
    }

    // Counter wraps at update
    s->cnt_shadow = 0u;
    s->cnt_epoch_ns = now;

    // Set UIF + possibly raise IRQ
    tim3_set_uif_and_irq(s);

    // Rearm next update
    tim3_schedule_next_update(s, now);
}

static inline uint32_t tim3_sr_read_value(const tim3_state_t *s) {
    uint32_t v = TIM3_SR_FIXED_MASK;
    if (s->sr_var & TIM_SR_UIF) {
        v |= TIM_SR_UIF;
    }
    return v;
}

// Accept addr as either offset or absolute; normalize to offset.
static inline uint64_t tim3_norm_off(uint64_t addr) {
    if (addr >= TIM3_BASE_ADDR && addr < (TIM3_BASE_ADDR + 0x400ULL)) {
        return addr - TIM3_BASE_ADDR;
    }
    return addr;
}

// -----------------------------------------------------------------------------
// MMIO callbacks
// -----------------------------------------------------------------------------
static uint64_t tim3_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc) {
    tim3_state_t *s = (tim3_state_t *)opaque;
    (void)pc;
    (void)opaque;
    uint64_t off = tim3_norm_off((uint64_t)addr);
    uint64_t now = vtime_now_ns();

    uint32_t r32 = 0;

    switch (off) {
        case TIM3_CR1_OFF:
            r32 = s->cr1;
            break;

        case TIM3_DIER_OFF:
            r32 = s->dier;
            break;

        case TIM3_SR_OFF:
            r32 = tim3_sr_read_value(s);
            break;

        case TIM3_CNT_OFF:
            r32 = tim3_compute_cnt(s, now);
            break;

        case TIM3_PSC_OFF:
            r32 = s->psc;
            break;

        case TIM3_ARR_OFF:
            r32 = s->arr;
            break;

        case TIM3_EGR_OFF:
            // EGR is write-only in many STM32 timers; return 0 is fine.
            r32 = 0;
            break;

        default:
            // Unmodeled registers return 0
            r32 = 0;
            break;
    }

    // Size handling (little-endian, basic masking)
    if (size == 1) return (uint8_t)(r32 & 0xFFu);
    if (size == 2) return (uint16_t)(r32 & 0xFFFFu);
    return (uint64_t)r32;
}

static void tim3_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc) {
    tim3_state_t *s = (tim3_state_t *)opaque;
    (void)pc;
    (void)opaque;
    uint64_t off = tim3_norm_off((uint64_t)addr);
    uint64_t now = vtime_now_ns();

    // Normalize writes by size
    uint32_t v32;
    if (size == 1) v32 = (uint32_t)(value & 0xFFu);
    else if (size == 2) v32 = (uint32_t)(value & 0xFFFFu);
    else v32 = (uint32_t)(value & 0xFFFFFFFFu);

    switch (off) {
        case TIM3_CR1_OFF: {
            // If toggling enable, latch CNT appropriately and (re)schedule.
            bool was_en = tim3_enabled(s);

            // Preserve only bits we care about (safe), but keep full value to satisfy RMW patterns.
            s->cr1 = v32;

            bool now_en = tim3_enabled(s);

            if (!was_en && now_en) {
                // Starting: align CNT epoch and arm next update based on current CNT/ARR/PSC.
                tim3_latch_cnt(s, now);
                tim3_schedule_next_update(s, now);
            } else if (was_en && !now_en) {
                // Stopping: latch CNT so reads become stable.
                tim3_latch_cnt(s, now);
            } else if (was_en && now_en) {
                // Still running: if timing-related bits changed, reschedule conservatively.
                tim3_schedule_next_update(s, now);
            }
            break;
        }

        case TIM3_PSC_OFF:
            s->psc = v32;
            if (tim3_enabled(s)) {
                tim3_schedule_next_update(s, now);
            }
            break;

        case TIM3_ARR_OFF:
            s->arr = v32;
            if (tim3_enabled(s)) {
                tim3_schedule_next_update(s, now);
            }
            break;

        case TIM3_DIER_OFF:
            s->dier = v32;
            // If UIF already set and UIE becomes enabled, real hardware would pend an IRQ.
            // We emulate that edge by raising immediately.
            if ((s->dier & TIM_DIER_UIE) && (s->sr_var & TIM_SR_UIF) && tim3_enabled(s)) {
                TIM3_RAISE_LINE();
            }
            break;

        case TIM3_SR_OFF: {
            // Trace shows firmware clears UIF by writing 0xFFFFFFFE (bit0 cleared).
            // For implemented flags: writing 0 clears; writing 1 leaves unchanged.
            if ((v32 & TIM_SR_UIF) == 0u) {
                s->sr_var &= ~TIM_SR_UIF;
            }
            // Ignore other bits; SR_FIXED_MASK remains "always set" on reads.
            break;
        }

        case TIM3_EGR_OFF: {
            // Only UG (bit0) observed.
            if (v32 & TIM_EGR_UG) {
                // UG reloads prescaler/ARR shadowing and typically resets CNT.
                tim3_latch_cnt(s, now);
                s->cnt_shadow = 0u;
                s->cnt_epoch_ns = now;

                // URS=1: UG should not generate update interrupt/DMA request.
                // We model: if URS==0 and updates not disabled, then set UIF (+ IRQ if enabled).
                if ((s->cr1 & TIM_CR1_URS) == 0u) {
                    tim3_set_uif_and_irq(s);
                }

                // Reschedule if running
                if (tim3_enabled(s)) {
                    tim3_schedule_next_update(s, now);
                }
            }
            break;
        }

        case TIM3_CNT_OFF:
            // Not seen in traces, but implement for completeness.
            tim3_latch_cnt(s, now);
            s->cnt_shadow = v32;
            s->cnt_epoch_ns = now;
            if (tim3_enabled(s)) {
                tim3_schedule_next_update(s, now);
            }
            break;

        default:
            // ignore unmodeled writes
            break;
    }
}

static void *tim3_init(const FdDevice *dev, const char *config_json, const FdHost *host) {
    (void)config_json;
    tim3_state_t *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->base = dev->ranges[0].base;
    s->host = host;
    s->name = dev->name;



    // Match observed init defaults / behavior
    s->cr1       = 0x00000000u;
    s->dier      = 0x00000000u;
    s->sr_var    = 0x00000000u;   // UIF cleared; fixed bits are OR'ed at read
    s->cnt_shadow= 0x00000000u;
    s->psc       = 0x00000000u;
    s->arr       = 0x0000FFFFu;   // safe default

    s->cnt_epoch_ns = vtime_now_ns();

    // One-shot timer; we re-arm it every update.
    s->update_timer_fd = qemu_plugin_timer_new_ns(tim3_update_cb, s);

    s->host->log(FD_LOG_LEVEL_DEBUG, s->name, "%s", "[tim3] init complete\n");
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = tim3_init,
    .read = tim3_read,
    .write = tim3_write,
};
