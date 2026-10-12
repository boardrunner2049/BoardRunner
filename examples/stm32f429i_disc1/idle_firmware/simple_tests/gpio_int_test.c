#ifdef TRAIN_GPIO_INT
/**
 * @file gpio_int_test.c
 * @brief Bare-metal pin-interrupt example for the STM32F429I-DISC1 board.
 *
 * The blue user button B1 (PA0) raises EXTI0 on its rising edge (press). The
 * interrupt service routine clears the pending flag and toggles LD3 (green,
 * PG13); the main loop blinks LD4 (red, PG14) to show the firmware runs.
 * The LEDs are driven through GPIOG MODER and ODR only.
 *
 * The system clock is the default 16MHz HSI.
 */

#include <stdint.h>

// RCC (Reset and Clock Control)
#define RCC_BASE            0x40023800
#define RCC_AHB1ENR         (*(volatile uint32_t*)(RCC_BASE + 0x30))
#define RCC_APB2ENR         (*(volatile uint32_t*)(RCC_BASE + 0x44))

// GPIOA (user button on PA0)
#define GPIOA_BASE          0x40020000
#define GPIOA_MODER         (*(volatile uint32_t*)(GPIOA_BASE + 0x00))
#define GPIOA_PUPDR         (*(volatile uint32_t*)(GPIOA_BASE + 0x0C))

// GPIOG (LEDs)
#define GPIOG_BASE          0x40021800
#define GPIOG_MODER         (*(volatile uint32_t*)(GPIOG_BASE + 0x00))
#define GPIOG_ODR           (*(volatile uint32_t*)(GPIOG_BASE + 0x14))

// SYSCFG (EXTI line routing)
#define SYSCFG_BASE         0x40013800
#define SYSCFG_EXTICR1      (*(volatile uint32_t*)(SYSCFG_BASE + 0x08))

// EXTI
#define EXTI_BASE           0x40013C00
#define EXTI_IMR            (*(volatile uint32_t*)(EXTI_BASE + 0x00))
#define EXTI_RTSR           (*(volatile uint32_t*)(EXTI_BASE + 0x08))
#define EXTI_FTSR           (*(volatile uint32_t*)(EXTI_BASE + 0x0C))
#define EXTI_PR             (*(volatile uint32_t*)(EXTI_BASE + 0x14))

// NVIC (Nested Vectored Interrupt Controller)
#define NVIC_ISER0          (*(volatile uint32_t*)(0xE000E100))

#define EXTI0_IRQn          6

#define LED_GREEN  13   // LD3, toggled by the interrupt
#define LED_RED    14   // LD4, blinked by the main loop

static volatile uint32_t presses;

static void delay(volatile unsigned int count) {
    while (count--);
}

/**
 * @brief  EXTI line 0 interrupt: the user button was pressed.
 */
void EXTI0_IRQHandler(void) {
    if (EXTI_PR & (1 << 0)) {
        // Clear the pending flag (write 1), or the ISR runs again at once.
        EXTI_PR = (1 << 0);
        presses++;
        GPIOG_ODR ^= (1 << LED_GREEN);
    }
}

/**
 * @brief  Main program.
 */
int gpio_int_test(void) {
    // 1. Enable the clocks of GPIOA, GPIOG and SYSCFG
    RCC_AHB1ENR |= (1 << 0) | (1 << 6);
    RCC_APB2ENR |= (1 << 14);

    // 2. PG13 and PG14 as outputs
    GPIOG_MODER &= ~((0x3 << (LED_GREEN*2)) | (0x3 << (LED_RED*2)));
    GPIOG_MODER |=  ((0x1 << (LED_GREEN*2)) | (0x1 << (LED_RED*2)));

    // 3. PA0 as input without pull (the board has its own pull-down)
    GPIOA_MODER &= ~(0x3 << 0);
    GPIOA_PUPDR &= ~(0x3 << 0);

    // 4. Route EXTI line 0 to port A, rising edge, unmasked
    SYSCFG_EXTICR1 &= ~(0xF << 0);
    EXTI_RTSR |= (1 << 0);
    EXTI_FTSR &= ~(1 << 0);
    EXTI_PR = (1 << 0);
    EXTI_IMR |= (1 << 0);

    // 5. Enable EXTI0 in the NVIC
    NVIC_ISER0 |= (1 << EXTI0_IRQn);

    // 6. Blink LD4; LD3 changes with every press
    while (1) {
        GPIOG_ODR ^= (1 << LED_RED);
        delay(200000);
    }
}
#endif /* TRAIN_GPIO_INT */
