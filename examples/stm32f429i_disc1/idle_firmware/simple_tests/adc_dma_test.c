#ifdef TRAIN_ADC_DMA

#include <stdint.h>

// ---------------------------------------------------------------------------
// Peripheral bases  (STM32F429)
// ---------------------------------------------------------------------------
#define RCC_BASE            0x40023800U
#define GPIOA_BASE          0x40020000U
#define USART1_BASE         0x40011000U
#define ADC1_BASE           0x40012000U
#define ADC_COMMON_BASE     0x40012300U
#define DMA2_BASE           0x40026400U

// RCC
#define RCC_AHB1ENR         (*(volatile uint32_t*)(RCC_BASE + 0x30))
#define RCC_APB2ENR         (*(volatile uint32_t*)(RCC_BASE + 0x44))
#define RCC_AHB1ENR_GPIOAEN (1U <<  0)
#define RCC_AHB1ENR_DMA2EN  (1U << 22)
#define RCC_APB2ENR_USART1EN (1U << 4)
#define RCC_APB2ENR_ADC1EN  (1U <<  8)

// GPIOA
#define GPIOA_MODER         (*(volatile uint32_t*)(GPIOA_BASE + 0x00))
#define GPIOA_AFRH          (*(volatile uint32_t*)(GPIOA_BASE + 0x24))

// USART1
#define USART1_SR           (*(volatile uint32_t*)(USART1_BASE + 0x00))
#define USART1_DR           (*(volatile uint32_t*)(USART1_BASE + 0x04))
#define USART1_BRR          (*(volatile uint32_t*)(USART1_BASE + 0x08))
#define USART1_CR1          (*(volatile uint32_t*)(USART1_BASE + 0x0C))
#define USART_SR_TXE        (1U <<  7)

// ADC1
#define ADC1_SR             (*(volatile uint32_t*)(ADC1_BASE + 0x00))
#define ADC1_CR1            (*(volatile uint32_t*)(ADC1_BASE + 0x04))
#define ADC1_CR2            (*(volatile uint32_t*)(ADC1_BASE + 0x08))
#define ADC1_SMPR1          (*(volatile uint32_t*)(ADC1_BASE + 0x0C))
#define ADC1_SQR1           (*(volatile uint32_t*)(ADC1_BASE + 0x2C))
#define ADC1_SQR3           (*(volatile uint32_t*)(ADC1_BASE + 0x34))
#define ADC1_DR             (*(volatile uint32_t*)(ADC1_BASE + 0x4C))

#define ADC_CR2_ADON        (1U <<  0)
#define ADC_CR2_CONT        (1U <<  1)
#define ADC_CR2_DMA         (1U <<  8)
#define ADC_CR2_DDS         (1U <<  9)
#define ADC_CR2_SWSTART     (1U << 30)

// ADC common
#define ADC_CCR             (*(volatile uint32_t*)(ADC_COMMON_BASE + 0x04))
#define ADC_CCR_TSVREFE     (1U << 23)

// DMA2 Stream 0
#define DMA2_LISR           (*(volatile uint32_t*)(DMA2_BASE + 0x00))
#define DMA2_LIFCR          (*(volatile uint32_t*)(DMA2_BASE + 0x08))
#define DMA2_S0CR           (*(volatile uint32_t*)(DMA2_BASE + 0x10))
#define DMA2_S0NDTR         (*(volatile uint32_t*)(DMA2_BASE + 0x14))
#define DMA2_S0PAR          (*(volatile uint32_t*)(DMA2_BASE + 0x18))
#define DMA2_S0M0AR         (*(volatile uint32_t*)(DMA2_BASE + 0x1C))

#define DMA_LISR_TCIF0      (1U <<  5)
#define DMA_LIFCR_CLEAR_S0  ((1U << 0) | (1U << 2) | (1U << 3) | (1U << 4) | (1U << 5))

#define DMA_SxCR_EN         (1U <<  0)
#define DMA_SxCR_CIRC       (1U <<  8)
#define DMA_SxCR_MINC       (1U << 10)
#define DMA_SxCR_PSIZE_16   (1U << 11)  // PSIZE = 01
#define DMA_SxCR_MSIZE_16   (1U << 13)  // MSIZE = 01
// CHSEL = 0 (channel 0 = ADC1 on DMA2 Stream 0), so no bits set

// ---------------------------------------------------------------------------
// Sample buffer — filled by DMA. Not initialized statically so the linker
// places it in .bss; adc_dma_init() zeros it explicitly.
// ---------------------------------------------------------------------------
#define SAMPLE_COUNT        16
static volatile uint16_t dma_buffer[SAMPLE_COUNT];

// ---------------------------------------------------------------------------
// UART primitives (verdict channel only, no self-tests)
// ---------------------------------------------------------------------------
static void uart_send_char(char c) {
    while (!(USART1_SR & USART_SR_TXE)) { }
    USART1_DR = (uint32_t)c;
}

static void uart_send_string(const char *s) {
    while (*s) uart_send_char(*s++);
}

static void uart_send_hex16(uint16_t v) {
    static const char hex[] = "0123456789ABCDEF";
    uart_send_char(hex[(v >> 12) & 0xF]);
    uart_send_char(hex[(v >>  8) & 0xF]);
    uart_send_char(hex[(v >>  4) & 0xF]);
    uart_send_char(hex[ v        & 0xF]);
}

static void uart_send_dec(uint32_t v) {
    char buf[11];
    int n = 0;
    if (v == 0) { uart_send_char('0'); return; }
    while (v && n < (int)sizeof(buf)) { buf[n++] = '0' + (v % 10); v /= 10; }
    while (n--) uart_send_char(buf[n]);
}

static void uart_init(void) {
    RCC_AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    GPIOA_MODER &= ~((3U << 18) | (3U << 20));
    GPIOA_MODER |=  ((2U << 18) | (2U << 20));   // AF mode PA9, PA10
    GPIOA_AFRH  &= ~((0xFU << 4) | (0xFU << 8));
    GPIOA_AFRH  |=  ((7U    << 4) | (7U    << 8)); // AF7 -> USART1
    RCC_APB2ENR |= RCC_APB2ENR_USART1EN;
    USART1_BRR = 0x8B;                            // 115200 @ 16 MHz
    USART1_CR1 = (1U << 13) | (1U << 3) | (1U << 2); // UE|TE|RE
}

// ---------------------------------------------------------------------------
// ADC1 + DMA2 setup: continuous conversion of VREFINT (channel 17), DMA-driven
// into a circular 16-sample RAM buffer.
// ---------------------------------------------------------------------------
static void adc_dma_init(void) {
    RCC_AHB1ENR |= RCC_AHB1ENR_DMA2EN;
    RCC_APB2ENR |= RCC_APB2ENR_ADC1EN;

    for (int i = 0; i < SAMPLE_COUNT; ++i) dma_buffer[i] = 0;

    // ADC common: enable VREFINT / temperature-sensor path
    ADC_CCR = ADC_CCR_TSVREFE;

    // ADC1 regular sequence: 1 conversion, VREFINT (channel 17)
    ADC1_SQR1  = 0;                                  // L = 0 -> 1 conversion
    ADC1_SQR3  = 17U;                                // SQ1 = channel 17
    ADC1_SMPR1 = (7U << ((17 - 10) * 3));            // SMP17 = 480 cycles
    ADC1_CR1   = 0;                                  // 12-bit resolution
    ADC1_CR2   = ADC_CR2_CONT | ADC_CR2_DMA | ADC_CR2_DDS;

    // DMA2 stream 0: disable, clear flags, then program
    DMA2_S0CR = 0;
    while (DMA2_S0CR & DMA_SxCR_EN) { }
    DMA2_LIFCR = DMA_LIFCR_CLEAR_S0;

    DMA2_S0PAR  = (uint32_t)&ADC1_DR;
    DMA2_S0M0AR = (uint32_t)dma_buffer;
    DMA2_S0NDTR = SAMPLE_COUNT;

    DMA2_S0CR = DMA_SxCR_PSIZE_16
              | DMA_SxCR_MSIZE_16
              | DMA_SxCR_MINC
              | DMA_SxCR_CIRC;
    DMA2_S0CR |= DMA_SxCR_EN;

    // Power up ADC, brief stabilization, then software-trigger first conversion
    ADC1_CR2 |= ADC_CR2_ADON;
    for (volatile int i = 0; i < 20000; ++i) { }
    ADC1_CR2 |= ADC_CR2_SWSTART;
}

// ---------------------------------------------------------------------------
// Verdict logic
// ---------------------------------------------------------------------------
static int wait_for_transfer_complete(void) {
    for (uint32_t i = 0; i < 5000000U; ++i) {
        if (DMA2_LISR & DMA_LISR_TCIF0) return 1;
    }
    return 0;
}

// Returns 1 and writes mean to *out_mean if buffer looks like real samples.
// Failure modes we expect from trace-derived models:
//   - buffer entirely 0 (no qemu_plugin_write_memory in the DMA model)
//   - buffer partially updated (NDTR wraparound not modeled)
//   - buffer contains ADC1_DR trace constants (model echoes trace values)
static int check_buffer(uint32_t *out_mean) {
    uint32_t sum = 0;
    for (int i = 0; i < SAMPLE_COUNT; ++i) {
        uint16_t v = dma_buffer[i];
        if (v == 0) return 0;               // any zero sample => failure
        sum += v;
    }
    uint32_t mean = sum / SAMPLE_COUNT;
    if (out_mean) *out_mean = mean;
    return (mean >= 500U) && (mean <= 3000U);   // VREFINT ≈ 1500 on 3.3V ref
}

static void dump_buffer(void) {
    uart_send_string("BUF=");
    for (int i = 0; i < SAMPLE_COUNT; ++i) {
        if (i) uart_send_char(',');
        uart_send_hex16(dma_buffer[i]);
    }
    uart_send_string("\r\n");
}

int adc_dma_test(void) {
    __asm volatile ("nop");
    __asm volatile ("nop");

    uart_init();
    uart_send_string("ADC_DMA_START\r\n");

    adc_dma_init();

    if (!wait_for_transfer_complete()) {
        uart_send_string("ADC_DMA_FAIL: no TCIF\r\n");
        dump_buffer();
        for (;;) { }
    }

    uint32_t mean = 0;
    if (!check_buffer(&mean)) {
        uart_send_string("ADC_DMA_FAIL: buffer check\r\n");
        dump_buffer();
        for (;;) { }
    }

    uart_send_string("ADC_DMA_OK avg=");
    uart_send_dec(mean);
    uart_send_string("\r\n");
    uart_send_string("SUCCESSFULLY REHOSTED!\r\n");

    for (;;) { }
    return 0;
}

#endif /* TRAIN_ADC_DMA */
