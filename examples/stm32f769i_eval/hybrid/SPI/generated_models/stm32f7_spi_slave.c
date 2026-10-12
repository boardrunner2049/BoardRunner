#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

#include <vio/slave.h>

// The second board of the SPI FullDuplex example, as an SPI slave: it answers
// one transaction of 97 bytes with its message, then stays idle.

const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;

// --- Slave State and Data ---

// This is the buffer the slave firmware arms for transmission.
static const uint8_t tx_message[] = "****SPI - Two Boards communication based on Polling **** SPI Message ******** SPI Message ******** SPI Message ****";

// The firmware main.c defines BUFFERSIZE as (COUNTOF(aTxBuffer) - 1).
// sizeof(tx_message) is 98 (including the null terminator).
// (COUNTOF(aTxBuffer) - 1) is (98 - 1) = 97.
// The firmware explicitly sends 97 bytes, excluding the null terminator.
#define FIRMWARE_BUFFER_SIZE 97

typedef struct {
    // This buffer will store the bytes received from the master.
    uint8_t rx_buffer[FIRMWARE_BUFFER_SIZE];
    // Tracks the current byte index within the transaction.
    uint16_t transfer_idx;
    // Tracks the SPI Chip Select (CS) state.
    bool is_chip_selected;
    // Tracks if the one-and-only transaction has been completed.
    // This is the key state variable to model the firmware's one-shot behavior.
    bool transaction_completed;
} Stm32f7SpiSlave;

void *vio_spi_slave_init(const char *name, const char *config_json) {
    (void)name;
    (void)config_json;
    return calloc(1, sizeof(Stm32f7SpiSlave));
}

// --- SPI Slave API Implementations ---

/**
 * @brief Callback to inform the slave model of its Chip Select (CS) state.
 * @param level 0 for active (LOW), 1 for inactive (HIGH).
 */
void vio_spi_slave_set_cs(void *ctx, int level) {
    Stm32f7SpiSlave *s = ctx;
    if (level == 0) {
        // CS is asserted (active LOW).
        s->is_chip_selected = true;

        // Per SPI protocol (CPHA=0), a falling CS edge marks the
        // beginning of a new transaction. We reset the index.
        s->transfer_idx = 0;
    } else {
        // CS is de-asserted (inactive HIGH).
        s->is_chip_selected = false;

        // If the transaction just finished (we sent all our bytes),
        // we mark it as completed. The firmware would now return
        // from HAL_SPI_TransmitReceive and enter while(1).
        if (s->transfer_idx >= FIRMWARE_BUFFER_SIZE && !s->transaction_completed) {
            s->transaction_completed = true;
        }
    }
}

/**
 * @brief Callback to handle a full-duplex SPI data transfer (one byte).
 * This function is called by the emulator for each byte the
 * master clocks out.
 * @param data The 8-bit data byte sent by the master (MOSI).
 * @return The 8-bit data byte sent by the slave (MISO).
 */
uint32_t vio_spi_slave_transfer(void *ctx, uint32_t data) {
    Stm32f7SpiSlave *s = ctx;
    // If CS is not active, MISO is high-impedance (returns 0xFF).
    if (!s->is_chip_selected) {
        return 0xFF;
    }

    // If the one-shot transaction is already complete, the firmware is
    // in while(1) and the SPI peripheral is no longer armed.
    if (s->transaction_completed) {
        return 0xFF;
    }

    // Check if we are still within the bounds of our one-shot transaction.
    if (s->transfer_idx < FIRMWARE_BUFFER_SIZE) {
        // Get the byte we need to send from our TX buffer.
        uint8_t byte_to_send = tx_message[s->transfer_idx];

        // Store the byte we received from the master.
        s->rx_buffer[s->transfer_idx] = (uint8_t)data;

        // Move to the next byte index.
        s->transfer_idx++;

        return byte_to_send;
    } else {
        // Master is sending more bytes than the firmware was armed for (97).
        // The HAL function would have returned, so the peripheral is idle.
        return 0xFF;
    }
}
