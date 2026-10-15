#include "sentinel/bind_config.h"
#include "sentinel/bind_nvs.h"

#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "bind_nvs";

esp_err_t sentinel_bind_nvs_load(sentinel_bind_config_t *cfg, bool *bound)
{
    if (!cfg || !bound) {
        return ESP_ERR_INVALID_ARG;
    }
    *bound = false;
    memset(cfg, 0, sizeof(*cfg));

    nvs_handle_t h;
    esp_err_t err = nvs_open(SENTINEL_BIND_NS, NVS_READONLY, &h);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    if (err != ESP_OK) {
        return err;
    }

    uint8_t b = 0;
    err = nvs_get_u8(h, SENTINEL_BIND_KEY_BOUND, &b);
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(h);
        return err;
    }
    *bound = (b == 1);

#define LOAD_STR(key, field)                                           \
    do {                                                               \
        size_t len = sizeof(cfg->field);                               \
        esp_err_t e = nvs_get_str(h, key, cfg->field, &len);           \
        if (e != ESP_OK && e != ESP_ERR_NVS_NOT_FOUND) {               \
            nvs_close(h);                                              \
            return e;                                                    \
        }                                                              \
    } while (0)

    LOAD_STR("host_id", host_id);
    LOAD_STR("camera_id", camera_id);
    LOAD_STR("static_ip", static_ip);
    LOAD_STR("gateway", gateway);
    LOAD_STR("netmask", netmask);
    LOAD_STR("wifi_bssid", wifi_bssid);
    LOAD_STR("mqtt_broker", mqtt_broker);
    LOAD_STR("mqtt_user", mqtt_username);
    LOAD_STR("mqtt_pass", mqtt_password);
    LOAD_STR("stream_tok", stream_token);
    LOAD_STR("wifi_ssid", wifi_ssid);
    LOAD_STR("wifi_psk", wifi_psk);

    uint8_t ch = 0;
    if (nvs_get_u8(h, "wifi_ch", &ch) == ESP_OK) {
        cfg->wifi_channel = ch;
    }
    uint16_t port = 0;
    if (nvs_get_u16(h, "mqtt_port", &port) == ESP_OK) {
        cfg->mqtt_port = port;
    }

    nvs_close(h);
    if (*bound && cfg->camera_id[0] == '\0') {
        ESP_LOGW(TAG, "bound flag set but config incomplete");
        *bound = false;
    }
    return ESP_OK;
}

esp_err_t sentinel_bind_nvs_save(const sentinel_bind_config_t *cfg)
{
    if (!cfg) {
        return ESP_ERR_INVALID_ARG;
    }

    nvs_handle_t h;
    esp_err_t err = nvs_open(SENTINEL_BIND_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }

    err = nvs_set_u8(h, SENTINEL_BIND_KEY_BOUND, 1);
    if (err != ESP_OK) {
        goto out;
    }

#define SAVE_STR(key, field) err = nvs_set_str(h, key, cfg->field); if (err != ESP_OK) goto out

    SAVE_STR("host_id", host_id);
    SAVE_STR("camera_id", camera_id);
    SAVE_STR("static_ip", static_ip);
    SAVE_STR("gateway", gateway);
    SAVE_STR("netmask", netmask);
    SAVE_STR("wifi_bssid", wifi_bssid);
    SAVE_STR("mqtt_broker", mqtt_broker);
    SAVE_STR("mqtt_user", mqtt_username);
    SAVE_STR("mqtt_pass", mqtt_password);
    SAVE_STR("stream_tok", stream_token);
    SAVE_STR("wifi_ssid", wifi_ssid);
    SAVE_STR("wifi_psk", wifi_psk);

    err = nvs_set_u8(h, "wifi_ch", cfg->wifi_channel);
    if (err != ESP_OK) {
        goto out;
    }
    err = nvs_set_u16(h, "mqtt_port", cfg->mqtt_port);
    if (err != ESP_OK) {
        goto out;
    }

    err = nvs_commit(h);
out:
    nvs_close(h);
    return err;
}

esp_err_t sentinel_bind_nvs_wipe(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(SENTINEL_BIND_NS, NVS_READWRITE, &h);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_erase_all(h);
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}
