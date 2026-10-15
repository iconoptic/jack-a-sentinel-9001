#pragma once

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "sentinel/bind_config.h"

esp_err_t sentinel_wifi_init_common(void);
esp_err_t sentinel_wifi_connect_bound(const sentinel_bind_config_t *bind, const char *wifi_ssid,
                                      const char *wifi_psk);
esp_err_t sentinel_wifi_wait_connected(TickType_t timeout);
