#include "sentinel/stream_http.h"
#include "sentinel/stream_stats.h"

#include <string.h>

#include "esp_camera.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "stream";

#define PART_BOUNDARY "sentinel_mjpeg_boundary"
static const char *STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static httpd_handle_t s_server;
static char s_token[128];
static bool s_client_active;
static uint32_t s_frame_interval_ms = 200;
static uint32_t s_frame_count;
static int64_t s_fps_window_start_us;
static float s_measured_fps;
static uint32_t s_dropped_frames;

static void note_stream_stats(void);

bool sentinel_stream_check_auth(httpd_req_t *req, const char *expected_token)
{
    if (!expected_token || expected_token[0] == '\0') {
        return false;
    }

    char auth[160];
    if (httpd_req_get_hdr_value_str(req, "Authorization", auth, sizeof(auth)) == ESP_OK) {
        const char *prefix = "Bearer ";
        if (strncasecmp(auth, prefix, strlen(prefix)) == 0) {
            return strcmp(auth + strlen(prefix), expected_token) == 0;
        }
    }

    char query[192];
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
        char tok[128];
        if (httpd_query_key_value(query, "token", tok, sizeof(tok)) == ESP_OK) {
            return strcmp(tok, expected_token) == 0;
        }
    }
    return false;
}

static esp_err_t snapshot_handler(httpd_req_t *req)
{
    if (!sentinel_stream_check_auth(req, s_token)) {
        httpd_resp_set_status(req, "401 Unauthorized");
        return httpd_resp_send(req, NULL, 0);
    }

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        return httpd_resp_send_500(req);
    }
    esp_err_t res = httpd_resp_set_type(req, "image/jpeg");
    if (res == ESP_OK) {
        res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
    }
    esp_camera_fb_return(fb);
    return res;
}

static esp_err_t stream_handler(httpd_req_t *req)
{
    if (!sentinel_stream_check_auth(req, s_token)) {
        httpd_resp_set_status(req, "401 Unauthorized");
        return httpd_resp_send(req, NULL, 0);
    }

    if (s_client_active) {
        httpd_resp_set_status(req, "503 Service Unavailable");
        return httpd_resp_send(req, "stream busy", HTTPD_RESP_USE_STRLEN);
    }
    s_client_active = true;

    esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
    char part_buf[128];
    while (res == ESP_OK) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGE(TAG, "fb_get failed");
            res = ESP_FAIL;
            break;
        }
        note_stream_stats();

        size_t hlen = snprintf(part_buf, sizeof(part_buf), STREAM_PART, fb->len);
        res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, part_buf, hlen);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
        }
        esp_camera_fb_return(fb);
        if (res != ESP_OK) {
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(s_frame_interval_ms));
    }
    s_client_active = false;
    return res;
}

static void note_stream_stats(void)
{
    s_frame_count++;
    int64_t now = esp_timer_get_time();
    if (s_fps_window_start_us == 0) {
        s_fps_window_start_us = now;
        return;
    }
    int64_t elapsed = now - s_fps_window_start_us;
    if (elapsed >= 1000000) {
        s_measured_fps = (float)s_frame_count * 1000000.f / (float)elapsed;
        s_frame_count = 0;
        s_fps_window_start_us = now;
    }
}

float sentinel_stream_get_fps(void)
{
    return s_measured_fps;
}

uint32_t sentinel_stream_get_dropped(void)
{
    return s_dropped_frames;
}

void sentinel_stream_note_drop(void)
{
    s_dropped_frames++;
}

void sentinel_stream_set_frame_interval_ms(uint32_t ms)
{
    if (ms > 0) {
        s_frame_interval_ms = ms;
    }
}

uint32_t sentinel_stream_get_frame_interval_ms(void)
{
    return s_frame_interval_ms;
}

esp_err_t sentinel_stream_http_start(const char *stream_token, httpd_handle_t *out_server)
{
    if (!stream_token || !out_server) {
        return ESP_ERR_INVALID_ARG;
    }
    strlcpy(s_token, stream_token, sizeof(s_token));
    if (s_server) {
        *out_server = s_server;
        return ESP_OK;
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    config.stack_size = 8192;
    config.lru_purge_enable = true;

    esp_err_t err = httpd_start(&s_server, &config);
    if (err != ESP_OK) {
        return err;
    }

    httpd_uri_t stream = {.uri = "/stream", .method = HTTP_GET, .handler = stream_handler};
    httpd_uri_t snap = {.uri = "/snapshot", .method = HTTP_GET, .handler = snapshot_handler};
    httpd_register_uri_handler(s_server, &stream);
    httpd_register_uri_handler(s_server, &snap);

    *out_server = s_server;
    ESP_LOGI(TAG, "HTTP /stream and /snapshot on port 80");
    return ESP_OK;
}

void sentinel_stream_http_stop(httpd_handle_t server)
{
    if (server) {
        httpd_stop(server);
    }
    s_server = NULL;
}
