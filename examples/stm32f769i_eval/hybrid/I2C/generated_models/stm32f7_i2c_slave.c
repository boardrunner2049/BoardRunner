#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <vio/slave.h>
#include <vio/i2c.h>

// The second board of the I2C TwoBoards example, as an I2C slave: it receives
// the master's message, and answers the master's read with its own message.

const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;

// --- Constants derived from the slave firmware ---

/**
 * @brief The 10-bit I2C address the slave will respond to.
 * Derived from #define I2C_ADDRESS 0x30F and hi2c1.Init.OwnAddress1 = 783.
 */
#define SLAVE_I2C_ADDRESS 0x30F

/**
 * @brief The hardcoded string the slave transmits to the master.
 * Derived from 'uint8_t aTxBuffer[]' in the slave firmware.
 */
static const uint8_t slave_tx_buffer_str[] = " ****I2C_TwoBoards communication based on Polling**** ****I2C_TwoBoards communication based on Polling**** ****I2C_TwoBoards communication based on Polling**** ";

/**
 * @brief Size of the communication buffers.
 * Derived from #define TXBUFFERSIZE (COUNTOF(aTxBuffer) - 1)
 */
#define BUFFER_SIZE (sizeof(slave_tx_buffer_str) - 1)

// --- Slave State ---

typedef struct {
    // Buffer to store data received from the master.
    uint8_t slave_rx_buffer[BUFFER_SIZE];
    // Index for writing into the buffer during a master-to-slave transfer.
    uint16_t slave_rx_idx;
    // Index for reading from the buffer during a slave-to-master transfer.
    uint16_t slave_tx_idx;
} Stm32f7I2cSlave;

void *vio_i2c_slave_init(const char *name, const char *config_json) {
    (void)name;
    (void)config_json;
    return calloc(1, sizeof(Stm32f7I2cSlave));
}

// --- Slave Function Implementations ---

/**
 * @brief Called when the master requests a byte of data (Master-Read
 * operation). It retrieves the next byte from the slave's *transmit* buffer
 * (the constant string).
 *
 * @return uint8_t The byte to be sent to the master.
 */
uint8_t vio_i2c_slave_recv(void *ctx) {
    Stm32f7I2cSlave *s = ctx;
    if (s->slave_tx_idx < BUFFER_SIZE) {
        // Read the byte from the hardcoded transmit buffer
        uint8_t data_to_send = slave_tx_buffer_str[s->slave_tx_idx];
        s->slave_tx_idx++;
        return data_to_send;
    }

    // Master is trying to read more data than the slave has.
    fprintf(stderr, "Error: Slave send buffer underrun!\n");
    return 0x00; // Send dummy data
}

/**
 * @brief Called when the master sends a byte of data (Master-Write
 * operation). It stores the received byte in the slave's *receive* buffer.
 *
 * @param data The byte received from the master.
 * @retval int Returns 0 for ACK (success) or 1 for NACK (e.g., buffer full).
 */
int vio_i2c_slave_send(void *ctx, uint8_t data) {
    Stm32f7I2cSlave *s = ctx;
    if (s->slave_rx_idx < BUFFER_SIZE) {
        s->slave_rx_buffer[s->slave_rx_idx++] = data;
        return 0; // Acknowledge the byte
    }

    // If the master sends more data than we have space for, NACK it.
    fprintf(stderr, "Error: Slave receive buffer overflow!\n");
    return 1; // NACK
}

/**
 * @brief Called on major bus events.
 * Based on the firmware logic (HAL_I2C_Slave_Receive followed by
 * HAL_I2C_Slave_Transmit), the slave performs two separate transactions.
 * We reset the appropriate index based on the transaction type.
 *
 * @retval int Returns 0 for success.
 */
int vio_i2c_slave_event(void *ctx, enum i2c_event event) {
    Stm32f7I2cSlave *s = ctx;
    switch (event) {
        case I2C_START_SEND:
            // Master is starting a WRITE (Slave will RECEIVE)
            // Reset the receive buffer index to prepare for new data.
            s->slave_rx_idx = 0;
            break;

        case I2C_START_RECV:
            // Master is starting a READ (Slave will SEND)
            // Reset the transmit buffer index to send from the beginning.
            s->slave_tx_idx = 0;
            break;

        case I2C_FINISH:
            // Transaction finished (STOP condition)
            break;

        case I2C_NACK:
            // Master NACK'd a byte from the slave
            break;

        default:
            break;
    }
    return 0; // Success
}
