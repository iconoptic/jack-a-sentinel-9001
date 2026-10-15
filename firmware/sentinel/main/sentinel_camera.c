#include "sentinel_camera.h"

#include "camera_pinout.h"
#include "esp_camera.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sentinel/bind_config.h"
#include "sentinel/mqtt_cmd.h"
#include "sentinel/stream_stats.h"

static const char *TAG = "camera";

static int s_jpeg_quality = 15;
static uint32_t s_min_frame_interval_ms = 200;
static uint32_t s_camera_failures;
static const uint32_t s_max_camera_failures = 10;

static void apply_mode(sentinel_stream_mode_t mode)
{
    if (mode == SENTINEL_MODE_ARMED) {
        s_jpeg_quality = 10;
        s_min_frame_interval_ms = 66;
    } else {
        s_jpeg_quality = 15;
        s_min_frame_interval_ms = 200;
    }
    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor) {
        sensor->set_quality(sensor, s_jpeg_quality);
    }
}

esp_err_t sentinel_camera_init(void)
{
    camera_config_t config = {
        .pin_pwdn = CAM_PIN_PWDN,
        .pin_reset = CAM_PIN_RESET,
        .pin_xclk = CAM_PIN_XCLK,
        .pin_sccb_sda = CAM_PIN_SIOD,
        .pin_sccb_scl = CAM_PIN_SIOC,
        .pin_d7 = CAM_PIN_D7,
        .pin_d6 = CAM_PIN_D6,
        .pin_d5 = CAM_PIN_D5,
        .pin_d4 = CAM_PIN_D4,
        .pin_d3 = CAM_PIN_D3,
        .pin_d2 = CAM_PIN_D2,
        .pin_d1 = CAM_PIN_D1,
        .pin_d0 = CAM_PIN_D0,
        .pin_vsync = CAM_PIN_VSYNC,
        .pin_href = CAM_PIN_HREF,
        .pin_pclk = CAM_PIN_PCLK,
        .xclk_freq_hz = 20000000,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = FRAMESIZE_HD,
        .jpeg_quality = s_jpeg_quality,
        .fb_count = 2,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_LATEST,
    };

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init: %s", esp_err_to_name(err));
        return err;
    }

    sensor_t *sensor = esp_camera_sensor_get();
    if (!sensor) {
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "Sensor PID 0x%04x", sensor->id.PID);
    if (sensor->id.PID != SENTINEL_EXPECTED_SENSOR_PID) {
        ESP_LOGE(TAG, "Unexpected sensor PID — expected 0x%04x", SENTINEL_EXPECTED_SENSOR_PID);
        return ESP_ERR_NOT_SUPPORTED;
    }
    apply_mode(SENTINEL_MODE_IDLE);
    return ESP_OK;
}

void sentinel_camera_on_mode(sentinel_stream_mode_t mode)
{
    apply_mode(mode);
}

uint32_t sentinel_camera_min_interval_ms(void)
{
    return s_min_frame_interval_ms;
}

void sentinel_camera_note_failure(void)
{
    s_camera_failures++;
    if (s_camera_failures >= s_max_camera_failures) {
        ESP_LOGE(TAG, "Too many camera errors — rebooting");
        esp_restart();
    }
}

void sentinel_camera_note_success(void)
{
    s_camera_failures = 0;
}
