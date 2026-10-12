#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <vio/slave.h>
#include <vio/i2c.h>

// The second STM32F4 board of the I2C TwoBoards example, as an I2C slave:
// it stores what the master sends and echoes it back when the master reads.

const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;

// --- Constants derived from the master firmware ---

/**
 * @brief The 10-bit I2C address the slave will respond to.
 */
#define SLAVE_I2C_ADDRESS 0x30F

/**
 * @brief Size of the communication buffer.
 */
#define BUFFER_SIZE 175

// --- Slave State ---

typedef struct {
    // Buffer to store data received from the master, which will then be echoed back.
    uint8_t slave_buffer[BUFFER_SIZE];
    // Index for writing into the buffer during a master-to-slave transfer.
    uint16_t slave_rx_idx;
    // Index for reading from the buffer during a slave-to-master transfer.
    uint16_t slave_tx_idx;
} Stm32f4I2cSlave;

void *vio_i2c_slave_init(const char *name, const char *config_json) {
    (void)name;
    (void)config_json;
    return calloc(1, sizeof(Stm32f4I2cSlave));
}

// --- Slave Function Implementations ---

/**
 * @brief Called whenever the master requests a byte of data.
 * It retrieves the next byte from the local buffer to send back to the master.
 *
 * @return uint8_t The byte to be sent to the master.
 */
uint8_t vio_i2c_slave_recv(void *ctx) {
    Stm32f4I2cSlave *s = ctx;
    if (s->slave_tx_idx < BUFFER_SIZE) {
        // Read the byte first, then increment the index.
        uint8_t data_to_send = s->slave_buffer[s->slave_tx_idx];
        s->slave_tx_idx++;
        return data_to_send;
    }
    fprintf(stderr, "Error: Slave send buffer underrun!\n");
    return 0x00;
}

/**
 * @brief Called whenever the master sends a byte of data.
 * It stores the received byte in a local buffer.
 *
 * @param data The byte received from the master.
 * @retval int Returns 0 for ACK (success) or 1 for NACK (e.g., buffer full).
 */
int vio_i2c_slave_send(void *ctx, uint8_t data) {
    Stm32f4I2cSlave *s = ctx;
    if (s->slave_rx_idx < BUFFER_SIZE) {
        s->slave_buffer[s->slave_rx_idx++] = data;
        return 0; // Acknowledge the byte
    }
    // If the master sends more data than we have space for, NACK it.
    fprintf(stderr, "Error: Slave receive buffer overflow!\n");
    return 1;
}

/**
 * @brief Called on bus events like START or STOP.
 * We use this to reset the buffer pointers, preparing the slave for a new transaction.
 *
 * @retval int Returns 0 for success.
 */
int vio_i2c_slave_event(void *ctx, enum i2c_event event) {
    Stm32f4I2cSlave *s = ctx;
    (void)event;
    // The master firmware completes a full transmit sequence, then initiates a
    // new receive sequence. Resetting both buffer indices on any new event
    // correctly prepares the slave to first receive the whole message, and then
    // send it back from the beginning.
    s->slave_rx_idx = 0;
    s->slave_tx_idx = 0;
    return 0;
}
