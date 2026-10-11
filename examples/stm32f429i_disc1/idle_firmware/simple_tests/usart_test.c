#ifdef TRAIN_USART

#define RCC_BASE     0x40023800
#define GPIOA_BASE   0x40020000
#define GPIOG_BASE   0x40021800
#define USART1_BASE  0x40011000

// RCC registers
#define RCC_AHB1ENR  (*(volatile unsigned int*)(RCC_BASE + 0x30))
#define RCC_APB2ENR  (*(volatile unsigned int*)(RCC_BASE + 0x44))

// GPIOA registers
#define GPIOA_MODER  (*(volatile unsigned int*)(GPIOA_BASE + 0x00))
#define GPIOA_AFRH   (*(volatile unsigned int*)(GPIOA_BASE + 0x24))

// GPIOG registers (on-board LEDs: PG13 = LD3 green, PG14 = LD4 red)
#define GPIOG_MODER  (*(volatile unsigned int*)(GPIOG_BASE + 0x00))
#define GPIOG_BSRR   (*(volatile unsigned int*)(GPIOG_BASE + 0x18))

#define LED_GREEN_PIN  13
#define LED_GREEN_SET  (1U << LED_GREEN_PIN)
#define LED_GREEN_RST  (1U << (LED_GREEN_PIN + 16))

// USART1 registers
#define USART1_SR    (*(volatile unsigned int*)(USART1_BASE + 0x00))
#define USART1_DR    (*(volatile unsigned int*)(USART1_BASE + 0x04))
#define USART1_BRR   (*(volatile unsigned int*)(USART1_BASE + 0x08))
#define USART1_CR1   (*(volatile unsigned int*)(USART1_BASE + 0x0C))

#define USART_SR_TXE   (1U << 7)
#define USART_SR_TC    (1U << 6)
#define USART_SR_RXNE  (1U << 5)
#define USART_SR_ORE   (1U << 3)

#define USART_CR1_UE      (1U << 13)
#define USART_CR1_M       (1U << 12)
#define USART_CR1_RXNEIE  (1U << 5)
#define USART_CR1_TE      (1U << 3)
#define USART_CR1_RE      (1U << 2)

static void led_init(void) {
    RCC_AHB1ENR |= (1U << 6);           // GPIOGEN
    GPIOG_MODER &= ~(3U << (LED_GREEN_PIN * 2));
    GPIOG_MODER |=  (1U << (LED_GREEN_PIN * 2)); // output
    GPIOG_BSRR   =  LED_GREEN_RST;      // start OFF (failure state)
}

static void led_green_on(void)  { GPIOG_BSRR = LED_GREEN_SET; }
static void led_green_off(void) { GPIOG_BSRR = LED_GREEN_RST; }

static void uart_send_char(char c) {
    while (!(USART1_SR & USART_SR_TXE)) { }
    USART1_DR = c;
}

static char uart_receive_char(void) {
    while (!(USART1_SR & USART_SR_RXNE)) { }
    return (char)USART1_DR;
}

static void uart_send_string(const char *s) {
    while (*s) uart_send_char(*s++);
}

static void uart_init(void) {
    RCC_AHB1ENR |= (1U << 0);           // GPIOAEN
    GPIOA_MODER &= ~((3U << 18) | (3U << 20));
    GPIOA_MODER |=  ((2U << 18) | (2U << 20));   // PA9, PA10 -> AF
    GPIOA_AFRH  &= ~((0xFU << 4) | (0xFU << 8));
    GPIOA_AFRH  |=  ((7U    << 4) | (7U    << 8)); // AF7

    RCC_APB2ENR |= (1U << 4);           // USART1EN
    USART1_BRR = 0x8B;                  // 115200 @ 16 MHz
    USART1_CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

// ---------------------------------------------------------------------------
// Self-tests. Each returns 1 on pass, 0 on fail. Together these exercise
// register behaviors that a trace-derived model typically stubs incorrectly:
//   - CR1 readback after RMW (must return what we wrote, not a trace constant)
//   - BRR readback with a value that never appeared in the training trace
//   - SR must report TXE|TC set once the peripheral is enabled and idle
//   - After a full TX completes, TC must return high without external help
//   - Word-length mode switch via CR1.M and restore
// ---------------------------------------------------------------------------

static int test_cr1_readback(void) {
    unsigned int orig = USART1_CR1;
    unsigned int probe = orig ^ USART_CR1_RXNEIE;   // toggle a bit the trace never set
    USART1_CR1 = probe;
    if (USART1_CR1 != probe) { USART1_CR1 = orig; return 0; }
    USART1_CR1 = orig;
    return USART1_CR1 == orig;
}

static int test_brr_readback(void) {
    unsigned int orig = USART1_BRR;
    unsigned int probe = 0x0000ABCDU;               // never seen in trace
    USART1_BRR = probe;
    int ok = (USART1_BRR == probe);
    USART1_BRR = orig;
    return ok && (USART1_BRR == orig);
}

static int test_sr_idle_flags(void) {
    unsigned int sr = USART1_SR;
    return (sr & USART_SR_TXE) && (sr & USART_SR_TC);
}

static int test_tc_after_send(void) {
    // Drain to a known idle state, then send a byte and wait for TC.
    for (volatile int i = 0; i < 2000; ++i) { }
    while (!(USART1_SR & USART_SR_TXE)) { }
    USART1_DR = 'X';
    // Bounded spin so a broken model doesn't hang the test forever.
    for (int i = 0; i < 200000; ++i) {
        if (USART1_SR & USART_SR_TC) return 1;
    }
    return 0;
}

static int test_mode_switch(void) {
    unsigned int orig = USART1_CR1;
    USART1_CR1 = orig | USART_CR1_M;    // switch to 9-bit words
    if (!(USART1_CR1 & USART_CR1_M)) { USART1_CR1 = orig; return 0; }
    USART1_CR1 = orig;                  // restore 8-bit
    return (USART1_CR1 & USART_CR1_M) == 0;
}

static int run_self_tests(void) {
    int ok = 1;
    ok &= test_sr_idle_flags();
    ok &= test_cr1_readback();
    ok &= test_brr_readback();
    ok &= test_tc_after_send();
    ok &= test_mode_switch();
    return ok;
}

// ---------------------------------------------------------------------------
// Optional interactive protocol phase. Runs after the self-tests pass so a
// host driver can further exercise the model (echo, PONG, ORE probe). None
// of this is required for the LED verdict.
// ---------------------------------------------------------------------------

static void protocol_loop(void) {
    for (;;) {
        char c = uart_receive_char();
        switch (c) {
        case 'P':
            uart_send_string("PONG\r\n");
            break;
        case 'E':
            uart_send_char((USART1_SR & USART_SR_ORE) ? '1' : '0');
            uart_send_string("\r\n");
            break;
        case 'Q':
            return;
        default:
            uart_send_char(c);          // echo
            break;
        }
    }
}

int usart_test(void) {
    __asm volatile ("nop");
    __asm volatile ("nop");

    led_init();                         // green LED starts OFF = failure state
    uart_init();

    if (run_self_tests()) {
        led_green_on();                 // success: green LED ON
        uart_send_string("USART_OK\r\n");
        protocol_loop();
    } else {
        led_green_off();                // failure: leave LED OFF
        uart_send_string("USART_FAIL\r\n");
    }

    for (;;) { }
    return 0;
}

#endif /* TRAIN_USART */
