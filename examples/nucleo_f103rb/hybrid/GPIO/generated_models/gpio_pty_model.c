#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <fastdyn/device_model.h>
#include <vio/vio.h>

// --- Register Offsets ---
#define GPIO_CRL  0x00
#define GPIO_CRH  0x04
#define GPIO_IDR  0x08
#define GPIO_ODR  0x0C
#define GPIO_BSRR 0x10
#define GPIO_BRR  0x14
#define GPIO_LCKR 0x18

// --- Base Addresses (from trace analysis) ---
#define GPIOA_BASE 0x40010800
#define GPIOC_BASE 0x40011000

// --- PTY Commands ---
#define CMD_TOGGLE_BTN 'b'

typedef struct {
    uint32_t CRL;
    uint32_t CRH;
    uint32_t IDR;
    uint32_t ODR;
    uint32_t BSRR;
    uint32_t BRR;
    uint32_t LCKR;
} GPIO_PortState;

// Instance state
typedef struct {
    GPIO_PortState gpio_a;
    GPIO_PortState gpio_c;
    int pty_fd;
    const FdHost *host;
    const char *name;
} GpioState;

#define GPIO_LOG(s, msg) (s)->host->log(FD_LOG_LEVEL_DEBUG, (s)->name, "%s", (msg))

// Helper to write string to PTY
static void pty_log(GpioState *s, const char *msg) {
    if (s->pty_fd >= 0) {
        while (*msg) {
            api_pty_write_req(s->pty_fd, (uint8_t)*msg++);
        }
    }
}

// Initialize default register values (Reset values for STM32F1 GPIO)
static void reset_port(GPIO_PortState *p) {
    p->CRL  = 0x44444444;
    p->CRH  = 0x44444444;
    p->IDR  = 0x0000FFFF; // Default floating/pull-up assumption
    p->ODR  = 0x00000000;
    p->BSRR = 0x00000000;
    p->BRR  = 0x00000000;
    p->LCKR = 0x00000000;
}

// Check PTY for user input to simulate button press (PC13)
static void update_input_state(GpioState *s) {
    if (s->pty_fd < 0) return;

    uint8_t buf;
    if (api_pty_read_nonblock(s->pty_fd, &buf)) {
        if (buf == CMD_TOGGLE_BTN) {
            // Toggle PC13 bit in GPIOC IDR
            s->gpio_c.IDR ^= (1 << 13);

            // Feedback to user
            if (s->gpio_c.IDR & (1 << 13)) {
                pty_log(s, "GPIOC: Pin 13 Released (High)\r\n");
                GPIO_LOG(s, "GPIOC: Pin 13 Released (High)");
            } else {
                pty_log(s, "GPIOC: Pin 13 Pressed (Low)\r\n");
                GPIO_LOG(s, "GPIOC: Pin 13 Pressed (Low)");
            }
        }
    }
}

// Device Model for GPIO
static uint64_t gpio_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc) {
    (void)size;
    (void)pc;
    GpioState *s = opaque;
    GPIO_PortState *port = NULL;
    uint32_t offset = 0;

    // Decode Address
    if (addr >= GPIOA_BASE && addr < (GPIOA_BASE + 0x400)) {
        port = &s->gpio_a;
        offset = addr - GPIOA_BASE;
    } else if (addr >= GPIOC_BASE && addr < (GPIOC_BASE + 0x400)) {
        port = &s->gpio_c;
        offset = addr - GPIOC_BASE;

        // Update input state before read if accessing GPIOC
        update_input_state(s);
    } else {
        return 0; // Unhandled range
    }

    switch (offset) {
        case GPIO_CRL: return port->CRL;
        case GPIO_CRH: return port->CRH;
        case GPIO_IDR: return port->IDR;
        case GPIO_ODR: return port->ODR;
        case GPIO_LCKR: return port->LCKR;
        // BSRR and BRR are write-only usually, return 0
        case GPIO_BSRR: return 0;
        case GPIO_BRR: return 0;
        default:
            GPIO_LOG(s, "GPIO: Read from unknown register");
            return 0;
    }
}

static void gpio_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc) {
    (void)size;
    (void)pc;
    GpioState *s = opaque;
    GPIO_PortState *port = NULL;
    uint32_t offset = 0;
    bool is_gpio_a = false;

    // Decode Address
    if (addr >= GPIOA_BASE && addr < (GPIOA_BASE + 0x400)) {
        port = &s->gpio_a;
        offset = addr - GPIOA_BASE;
        is_gpio_a = true;
    } else if (addr >= GPIOC_BASE && addr < (GPIOC_BASE + 0x400)) {
        port = &s->gpio_c;
        offset = addr - GPIOC_BASE;
    } else {
        return; // Unhandled
    }

    switch (offset) {
        case GPIO_CRL:
            port->CRL = (uint32_t)value;
            break;
        case GPIO_CRH:
            port->CRH = (uint32_t)value;
            break;
        case GPIO_ODR:
            port->ODR = (uint32_t)value;
            break;
        case GPIO_BSRR: {
            port->BSRR = (uint32_t)value;
            uint32_t set_bits = value & 0xFFFF;
            uint32_t reset_bits = (value >> 16) & 0xFFFF;

            // Update ODR
            port->ODR |= set_bits;
            port->ODR &= ~reset_bits;

            // Observable: Check GPIOA Pin 5 (User LED)
            if (is_gpio_a) {
                if (set_bits & (1 << 5)) {
                    pty_log(s, "GPIOA: LED (PA5) -> ON\r\n");
                    GPIO_LOG(s, "GPIOA: LED (PA5) -> ON");
                }
                if (reset_bits & (1 << 5)) {
                    pty_log(s, "GPIOA: LED (PA5) -> OFF\r\n");
                    GPIO_LOG(s, "GPIOA: LED (PA5) -> OFF");
                }
            }
            break;
        }
        case GPIO_BRR: {
            port->BRR = (uint32_t)value;
            uint32_t reset_bits = value & 0xFFFF;
            port->ODR &= ~reset_bits;

            if (is_gpio_a && (reset_bits & (1 << 5))) {
                 pty_log(s, "GPIOA: LED (PA5) -> OFF\r\n");
                 GPIO_LOG(s, "GPIOA: LED (PA5) -> OFF");
            }
            break;
        }
        case GPIO_LCKR:
            port->LCKR = (uint32_t)value;
            break;
        default:
            GPIO_LOG(s, "GPIO: Write to unknown register");
            break;
    }
}

static void *gpio_init(const FdDevice *dev, const char *config_json, const FdHost *host) {
    (void)config_json;
    GpioState *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    s->host = host;
    s->name = dev->name;

    // Initialize state
    reset_port(&s->gpio_a);
    reset_port(&s->gpio_c);

    // Setup PTY for user interaction
    s->pty_fd = api_pty_fd_gen();
    if (s->pty_fd >= 0) {
        GPIO_LOG(s, "GPIO: PTY initialized at /tmp/usart1_pty");
        pty_log(s, "\r\n=== GPIO Interactive Model ===\r\n");
        pty_log(s, "Controls:\r\n");
        pty_log(s, "  'b' : Toggle PC13 (Button)\r\n");
        pty_log(s, "Watching:\r\n");
        pty_log(s, "  PA5 : LED Status\r\n");
        pty_log(s, "==============================\r\n");
    } else {
        GPIO_LOG(s, "GPIO: Failed to initialize PTY");
    }
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = gpio_init,
    .read = gpio_read,
    .write = gpio_write,
};
