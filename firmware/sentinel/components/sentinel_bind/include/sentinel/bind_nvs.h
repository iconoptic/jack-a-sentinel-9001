#pragma once

#include "esp_err.h"
#include "sentinel/bind_config.h"

esp_err_t sentinel_bind_nvs_load(sentinel_bind_config_t *cfg, bool *bound);
esp_err_t sentinel_bind_nvs_save(const sentinel_bind_config_t *cfg);
esp_err_t sentinel_bind_nvs_wipe(void);
