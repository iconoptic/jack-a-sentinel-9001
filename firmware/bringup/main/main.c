/*
 * Phase 1 bench bring-up: Wi-Fi + GET /stream MJPEG + serial telemetry.
 * Throwaway — product firmware lives in firmware/sentinel/ (Phase 3).
 */

#include "sdkconfig.h"

#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "camera_pinout.h"
#include "esp_camera.h"
#include "esp_chip_info.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "driver/temperature_sensor.h"

static const char *TAG = "bringup";

#ifndef WIFI_SSID
#define WIFI_SSID "CONFIGURE_ME"
#endif
#ifndef WIFI_PSK
#define WIFI_PSK "CONFIGURE_ME"
#endif

#define PART_BOUNDARY "123456789000000000000987654321"
static const char *STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static httpd_handle_t s_stream_server;
static bool s_http_started;
static SemaphoreHandle_t s_stats_lock;
static uint32_t s_frame_count;
static int64_t s_fps_window_start_us;
static float s_measured_fps;
static framesize_t s_framesize;
static int s_jpeg_quality = CONFIG_SENTINEL_BRINGUP_JPEG_QUALITY;
static temperature_sensor_handle_t s_temp_sensor;

static framesize_t framesize_from_kconfig(void)
{
#if CONFIG_SENTINEL_BRINGUP_FRAMESIZE_VGA
    return FRAMESIZE_VGA;
#elif CONFIG_SENTINEL_BRINGUP_FRAMESIZE_SVGA
    return FRAMESIZE_SVGA;
#elif CONFIG_SENTINEL_BRINGUP_FRAMESIZE_UXGA
    return FRAMESIZE_UXGA;
#else
    return FRAMESIZE_HD;
#endif
}

static const char *framesize_name(framesize_t fs)
{
    switch (fs) {
    case FRAMESIZE_VGA:
        return "VGA";
    case FRAMESIZE_SVGA:
        return "SVGA";
    case FRAMESIZE_HD:
        return "HD";
    case FRAMESIZE_UXGA:
        return "UXGA";
    default:
        return "?";
    }
}

static void note_frame_captured(void)
{
    if (xSemaphoreTake(s_stats_lock, pdMS_TO_TICKS(10)) != pdTRUE) {
        return;
    }
    s_frame_count++;
    int64_t now = esp_timer_get_time();
    if (s_fps_window_start_us == 0) {
        s_fps_window_start_us = now;
    } else {
        int64_t elapsed = now - s_fps_window_start_us;
        if (elapsed >= 1000000) {
            s_measured_fps = (float)s_frame_count * 1000000.f / (float)elapsed;
            s_frame_count = 0;
            s_fps_window_start_us = now;
        }
    }
    xSemaphoreGive(s_stats_lock);
}

static esp_err_t init_camera(void)
{
    s_framesize = framesize_from_kconfig();

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
        .frame_size = s_framesize,
        .jpeg_quality = s_jpeg_quality,
        .fb_count = 2,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_LATEST,
    };

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init failed: %s", esp_err_to_name(err));
        return err;
    }

    sensor_t *sensor = esp_camera_sensor_get();
    if (sensor) {
        ESP_LOGI(TAG, "Sensor PID 0x%04x", sensor->id.PID);
    }
    return ESP_OK;
}

static esp_err_t set_framesize(framesize_t fs)
{
    sensor_t *sensor = esp_camera_sensor_get();
    if (!sensor) {
        return ESP_FAIL;
    }
    if (sensor->set_framesize(sensor, fs) != 0) {
        return ESP_FAIL;
    }
    s_framesize = fs;
    return ESP_OK;
}

static void init_temp_sensor(void)
{
    temperature_sensor_config_t cfg = TEMPERATURE_SENSOR_CONFIG_DEFAULT(10, 80);
    if (temperature_sensor_install(&cfg, &s_temp_sensor) != ESP_OK) {
        ESP_LOGW(TAG, "On-chip temperature sensor unavailable");
        s_temp_sensor = NULL;
        return;
    }
    temperature_sensor_enable(s_temp_sensor);
}

static float read_chip_temp_c(void)
{
    if (!s_temp_sensor) {
        return NAN;
    }
    float temp = NAN;
    if (temperature_sensor_get_celsius(s_temp_sensor, &temp) != ESP_OK) {
        return NAN;
    }
    return temp;
}

static void wifi_init_sta(void)
{
    if (strcmp(WIFI_SSID, "CONFIGURE_ME") == 0) {
        ESP_LOGE(TAG, "Wi-Fi not configured — copy wifi.local.example to wifi.local and rebuild");
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, WIFI_SSID, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, WIFI_PSK, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_connect());

    ESP_LOGI(TAG, "Connecting to SSID \"%s\"...", WIFI_SSID);
}

static esp_err_t root_handler(httpd_req_t *req)
{
    const char *html =
        "<html><body>"
        "<h1>sentinel bringup</h1>"
        "<p><a href=\"/stream\">MJPEG stream</a></p>"
        "<p>Change size: "
        "<a href=\"/framesize?vga\">VGA</a> "
        "<a href=\"/framesize?svga\">SVGA</a> "
        "<a href=\"/framesize?hd\">HD</a> "
        "<a href=\"/framesize?uxga\">UXGA</a>"
        "</p></body></html>";
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, html, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t framesize_handler(httpd_req_t *req)
{
    char query[32] = {0};
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
        if (strstr(query, "vga")) {
            set_framesize(FRAMESIZE_VGA);
        } else if (strstr(query, "svga")) {
            set_framesize(FRAMESIZE_SVGA);
        } else if (strstr(query, "hd")) {
            set_framesize(FRAMESIZE_HD);
        } else if (strstr(query, "uxga")) {
            set_framesize(FRAMESIZE_UXGA);
        }
    }
    char resp[64];
    snprintf(resp, sizeof(resp), "framesize=%s\n", framesize_name(s_framesize));
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, resp, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t stream_handler(httpd_req_t *req)
{
    esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
    if (res != ESP_OK) {
        return res;
    }

    char part_buf[128];
    while (true) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGE(TAG, "esp_camera_fb_get failed");
            return ESP_FAIL;
        }

        note_frame_captured();

        if (res == ESP_OK) {
            size_t hlen = snprintf(part_buf, sizeof(part_buf), STREAM_PART, fb->len);
            res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
            if (res == ESP_OK) {
                res = httpd_resp_send_chunk(req, part_buf, hlen);
            }
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
        }
        esp_camera_fb_return(fb);
        if (res != ESP_OK) {
            break;
        }
    }
    return res;
}

static esp_err_t start_stream_server(void)
{
    if (s_http_started) {
        return ESP_OK;
    }
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    config.ctrl_port = 32768;
    config.stack_size = 8192;

    ESP_ERROR_CHECK(httpd_start(&s_stream_server, &config));

    httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = root_handler};
    httpd_uri_t stream = {.uri = "/stream", .method = HTTP_GET, .handler = stream_handler};
    httpd_uri_t fsize = {.uri = "/framesize", .method = HTTP_GET, .handler = framesize_handler};

    httpd_register_uri_handler(s_stream_server, &root);
    httpd_register_uri_handler(s_stream_server, &stream);
    httpd_register_uri_handler(s_stream_server, &fsize);

    s_http_started = true;
    ESP_LOGI(TAG, "HTTP server on port %d — GET /stream", config.server_port);
    return ESP_OK;
}

static void stats_task(void *arg)
{
    (void)arg;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(3000));

        sensor_t *sensor = esp_camera_sensor_get();
        uint16_t pid = sensor ? sensor->id.PID : 0;

        float fps = 0.f;
        if (xSemaphoreTake(s_stats_lock, pdMS_TO_TICKS(100)) == pdTRUE) {
            fps = s_measured_fps;
            xSemaphoreGive(s_stats_lock);
        }

        size_t heap = esp_get_free_heap_size();
        size_t psram = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
        float temp = read_chip_temp_c();

        if (isnan(temp)) {
            ESP_LOGI(TAG,
                     "pid=0x%04x framesize=%s fps=%.1f jpeg_q=%d heap=%u psram=%u temp=n/a",
                     pid, framesize_name(s_framesize), fps, s_jpeg_quality,
                     (unsigned)heap, (unsigned)psram);
        } else {
            ESP_LOGI(TAG,
                     "pid=0x%04x framesize=%s fps=%.1f jpeg_q=%d heap=%u psram=%u temp=%.1fC",
                     pid, framesize_name(s_framesize), fps, s_jpeg_quality,
                     (unsigned)heap, (unsigned)psram, temp);
        }
    }
}

static void on_got_ip(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    ip_event_got_ip_t *event = (ip_event_got_ip_t *)data;
    ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
    start_stream_server();
}

void app_main(void)
{
    s_stats_lock = xSemaphoreCreateMutex();

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    esp_chip_info_t chip;
    esp_chip_info(&chip);
    ESP_LOGI(TAG, "Chip: ESP32-S3, cores=%d, revision=%d", chip.cores, chip.revision);

    init_temp_sensor();
    ESP_ERROR_CHECK(init_camera());

    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &on_got_ip, NULL));
    wifi_init_sta();

    xTaskCreate(stats_task, "stats", 4096, NULL, 5, NULL);
}
