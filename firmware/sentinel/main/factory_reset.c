#include "factory_reset.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "factory_reset";

#define BOOT_GPIO GPIO_NUM_0
#define HOLD_MS 10000

bool factory_reset_boot_button_held(void)
{
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << BOOT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);

    int64_t start = esp_timer_get_time();
    while ((esp_timer_get_time() - start) < (int64_t)HOLD_MS * 1000) {
        if (gpio_get_level(BOOT_GPIO) != 0) {
            return false;
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    ESP_LOGW(TAG, "BOOT held %d ms at power-up — factory reset", HOLD_MS);
    return true;
}
