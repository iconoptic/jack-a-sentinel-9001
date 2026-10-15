#pragma once

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sentinel/bind_config.h"
#include "sentinel/mqtt_cmd.h"

typedef void (*sentinel_mqtt_mode_cb_t)(sentinel_stream_mode_t mode);

esp_err_t sentinel_mqtt_start(const sentinel_bind_config_t *bind, sentinel_mqtt_mode_cb_t mode_cb);
void sentinel_mqtt_stop(void);
void sentinel_mqtt_publish_factory_reset(void);
void sentinel_mqtt_tick(int64_t now_ms);
void sentinel_mqtt_telemetry_task(void *arg);
sentinel_stream_mode_t sentinel_mqtt_current_mode(void);
