#include "factory_reset.h"
#include "nvs_setup.h"
#include "sentinel_camera.h"
#include "sentinel_wifi.h"

#include "esp_log.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sentinel/bind_config.h"
#include "sentinel/bind_nvs.h"
#include "sentinel/mqtt_client.h"
#include "sentinel/prov.h"
#include "sentinel/stream_http.h"
#include "sentinel/stream_stats.h"

static const char *TAG = "sentinel";

static sentinel_bind_config_t s_bind;
static bool s_bound;
static httpd_handle_t s_http;

static void on_mode_change(sentinel_stream_mode_t mode)
{
    sentinel_camera_on_mode(mode);
    sentinel_stream_set_frame_interval_ms(sentinel_camera_min_interval_ms());
}

/*
 * Wi-Fi credentials for a BOUND board. Boards flashed by scripts/install-esp32.sh carry
 * them in the bind namespace. Boards bound over BLE keep them in the esp_wifi namespace
 * (written by network_provisioning), so fall back to that.
 */
static esp_err_t connect_bound(const sentinel_bind_config_t *bind)
{
    if (bind->wifi_ssid[0] != '\0') {
        return sentinel_wifi_connect_bound(bind, bind->wifi_ssid, bind->wifi_psk);
    }

    wifi_config_t wc = {0};
    if (esp_wifi_get_config(WIFI_IF_STA, &wc) != ESP_OK || wc.sta.ssid[0] == '\0') {
        ESP_LOGE(TAG, "No Wi-Fi credentials in bind NVS or esp_wifi storage");
        return ESP_ERR_NOT_FOUND;
    }
    return sentinel_wifi_connect_bound(bind, (const char *)wc.sta.ssid,
                                       (const char *)wc.sta.password);
}

static void start_bound_services(void)
{
    ESP_ERROR_CHECK(sentinel_stream_http_start(s_bind.stream_token, &s_http));
    ESP_ERROR_CHECK(sentinel_mqtt_start(&s_bind, on_mode_change));
    xTaskCreate(sentinel_mqtt_telemetry_task, "mqtt_telem", 4096, NULL, 5, NULL);
}

static void on_prov_bound(const sentinel_bind_config_t *cfg)
{
    ESP_LOGI(TAG, "Bind complete — stopping BLE provisioning");
    sentinel_prov_deinit();

    s_bind = *cfg;
    s_bound = true;

    if (connect_bound(&s_bind) != ESP_OK) {
        ESP_LOGE(TAG, "Static IP / Wi-Fi connect failed after bind");
        return;
    }

    ESP_ERROR_CHECK(sentinel_camera_init());
    start_bound_services();
}

static void run_unbound(void)
{
    ESP_LOGI(TAG, "UNBOUND — starting BLE provisioning");
    ESP_ERROR_CHECK(sentinel_prov_start(on_prov_bound));
}

static void run_bound(void)
{
    ESP_LOGI(TAG, "BOUND — camera_id=%s", s_bind.camera_id);

    ESP_ERROR_CHECK(esp_wifi_start());

    if (connect_bound(&s_bind) != ESP_OK) {
        ESP_LOGE(TAG, "Wi-Fi connect failed (no credentials means factory reset or reflash)");
        return;
    }

    ESP_ERROR_CHECK(sentinel_camera_init());
    start_bound_services();
}

static void do_factory_reset(void)
{
    sentinel_bind_config_t cfg;
    bool bound = false;
    if (sentinel_bind_nvs_load(&cfg, &bound) == ESP_OK && bound) {
        ESP_ERROR_CHECK(esp_wifi_start());
        if (connect_bound(&cfg) == ESP_OK) {
            sentinel_mqtt_start(&cfg, NULL);
            vTaskDelay(pdMS_TO_TICKS(500));
            sentinel_mqtt_publish_factory_reset();
            vTaskDelay(pdMS_TO_TICKS(500));
            sentinel_mqtt_stop();
        }
    }
    sentinel_bind_nvs_wipe();
    nvs_flash_erase();
    esp_restart();
}

void app_main(void)
{
    ESP_LOGI(TAG, "Sentinel firmware v1");

    ESP_ERROR_CHECK(sentinel_nvs_init());
    ESP_ERROR_CHECK(sentinel_wifi_init_common());

    if (factory_reset_boot_button_held()) {
        do_factory_reset();
    }

    ESP_ERROR_CHECK(sentinel_bind_nvs_load(&s_bind, &s_bound));

    if (s_bound) {
        run_bound();
    } else {
        run_unbound();
    }
}
