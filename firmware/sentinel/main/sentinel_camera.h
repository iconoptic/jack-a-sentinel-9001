#pragma once

#include "esp_err.h"
#include "sentinel/mqtt_cmd.h"

esp_err_t sentinel_camera_init(void);
void sentinel_camera_on_mode(sentinel_stream_mode_t mode);
uint32_t sentinel_camera_min_interval_ms(void);
void sentinel_camera_note_failure(void);
void sentinel_camera_note_success(void);
