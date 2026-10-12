#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

#include <vio/slave.h>

// The second STM32F4 board of the SPI TwoBoards example, as an SPI slave:
// it answers every transfer with the next byte of its message.

const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;

// --- Slave State and Data ---

static const uint8_t tx_message[] = "****SPI - Two Boards communication based on Polling **** SPI Message ******** SPI Message ******** SPI Message ****";
#define BUFFER_SIZE sizeof(tx_message)

typedef struct {
    uint8_t rx_buffer[BUFFER_SIZE];
    uint16_t transfer_idx;
    bool is_chip_selected;
} Stm32f4SpiSlave;

void *vio_spi_slave_init(const char *name, const char *config_json) {
    (void)name;
    (void)config_json;
    return calloc(1, sizeof(Stm32f4SpiSlave));
}

// --- Slave Functions ---

/**
 * @brief Callback to inform the slave of its Chip Select (CS) state.
 */
void vio_spi_slave_set_cs(void *ctx, int level) {
    Stm32f4SpiSlave *s = ctx;
    if (level == 0) { // Active-low CS
        s->is_chip_selected = true;
        // Do NOT reset the index here.
        // This allows the transaction to continue across multiple CS toggles.
    } else {
        s->is_chip_selected = false;
    }
}

/**
 * @brief Callback to handle a full-duplex SPI data transfer.
 */
uint32_t vio_spi_slave_transfer(void *ctx, uint32_t data) {
    Stm32f4SpiSlave *s = ctx;
    if (!s->is_chip_selected) {
        return 0xFF; // MISO is high-impedance when not selected
    }

    // Reset index if it goes out of bounds to loop the message
    if (s->transfer_idx >= BUFFER_SIZE) {
        s->transfer_idx = 0;
    }

    uint8_t byte_to_send = tx_message[s->transfer_idx];
    s->rx_buffer[s->transfer_idx] = (uint8_t)data;

    s->transfer_idx++;

    return byte_to_send;
}
