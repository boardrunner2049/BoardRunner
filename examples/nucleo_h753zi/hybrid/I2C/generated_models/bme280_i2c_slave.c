// bme280_i2c_slave.c
//
// Minimal stateful I2C slave model for a BME280-like device.
// Implements:
//   - register pointer write on first byte after I2C_START_SEND
//   - sequential register writes/reads with auto-increment
//   - CHIP_ID register at 0xD0 returning 0x60
//   - soft reset on write 0xB6 to 0xE0
//
// LibVIO slave interface (<vio/slave.h>), one instance per slave:
//   - vio_i2c_slave_init
//   - vio_i2c_slave_event
//   - vio_i2c_slave_send
//   - vio_i2c_slave_recv
//
// Build:
//   boardrunner build-models bme280_i2c_slave.c

#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include <vio/slave.h>

const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;

// ---- BME280 register map ----
#define REG_ID         0xD0
#define REG_RESET      0xE0
#define REG_CTRL_HUM   0xF2
#define REG_STATUS     0xF3
#define REG_CTRL_MEAS  0xF4
#define REG_CONFIG     0xF5
#define REG_DATA       0xF7

#define CHIP_ID_BME280 0x60
#define RESET_CMD      0xB6

typedef struct {
    uint8_t regs[256];
    bool    expect_reg_addr;   // next written byte is register pointer
    uint8_t reg_ptr;           // current register pointer
    bool    inited;
} bme280_state_t;


static void load_defaults(bme280_state_t *s)
{
    int i;

    memset(s->regs, 0, sizeof(s->regs));

    // Core identity
    s->regs[REG_ID] = CHIP_ID_BME280;

    // Control / status defaults
    s->regs[REG_CTRL_HUM]  = 0x00;
    s->regs[REG_STATUS]    = 0x00;
    s->regs[REG_CTRL_MEAS] = 0x00;
    s->regs[REG_CONFIG]    = 0x00;

    // Calibration blocks: stable example content
    for (i = 0; i < 26; i++) {
        s->regs[0x88 + i] = (uint8_t)(0x20 + i);
    }
    for (i = 0; i < 7; i++) {
        s->regs[0xE1 + i] = (uint8_t)(0x80 + i);
    }
    s->regs[0xA1] = 0x55;

    // Specific reference-friendly value
    s->regs[0x88] = 0x93;

    // Example measurement data: pressure(3), temperature(3), humidity(2)
    s->regs[0xF7] = 0x64;
    s->regs[0xF8] = 0x00;
    s->regs[0xF9] = 0x00;
    s->regs[0xFA] = 0x7A;
    s->regs[0xFB] = 0x00;
    s->regs[0xFC] = 0x00;
    s->regs[0xFD] = 0x40;
    s->regs[0xFE] = 0x00;

    s->expect_reg_addr = false;
    s->reg_ptr = 0x00;
}

void *vio_i2c_slave_init(const char *name, const char *config_json)
{
    (void)name;
    (void)config_json;
    bme280_state_t *s = calloc(1, sizeof(*s));
    if (!s) {
        return NULL;
    }
    load_defaults(s);
    s->inited = true;
    return s;
}

#ifdef __cplusplus
extern "C" {
#endif

// Return 0 for ACK, 1 for NACK.
int vio_i2c_slave_send(void *ctx, uint8_t data)
{
    uint8_t reg;

    bme280_state_t *s = ctx;

    if (s->expect_reg_addr) {
        s->reg_ptr = data;
        s->expect_reg_addr = false;
        return 0;
    }

    reg = s->reg_ptr;
    s->regs[reg] = data;

    if (reg == REG_RESET && data == RESET_CMD) {
        load_defaults(s);
        return 0;
    }

    s->reg_ptr = (uint8_t)(s->reg_ptr + 1);
    return 0;
}

uint8_t vio_i2c_slave_recv(void *ctx)
{
    uint8_t reg;
    uint8_t val;

    bme280_state_t *s = ctx;

    reg = s->reg_ptr;
    val = s->regs[reg];

    // Keep STATUS deterministic and idle
    if (reg == REG_STATUS) {
        val = 0x00;
    }

    s->reg_ptr = (uint8_t)(s->reg_ptr + 1);
    return val;
}

int vio_i2c_slave_event(void *ctx, enum i2c_event event)
{
    bme280_state_t *s = ctx;

    switch (event) {
    case I2C_START_SEND:
        // First byte of write phase is treated as the register pointer
        s->expect_reg_addr = true;
        break;

    case I2C_START_RECV:
        // Repeated-start read uses previously latched register pointer
        s->expect_reg_addr = false;
        break;

    case I2C_FINISH:
    case I2C_NACK:
    default:
        s->expect_reg_addr = false;
        break;
    }

    return 0;
}


#ifdef __cplusplus
}
#endif