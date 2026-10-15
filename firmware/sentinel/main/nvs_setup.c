#include "nvs_setup.h"

#include "esp_log.h"
#include "esp_partition.h"
#include "nvs_flash.h"

static const char *TAG = "nvs_setup";

esp_err_t sentinel_nvs_init(void)
{
    const esp_partition_t *nvs_keys = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS_KEYS, NULL);
    if (!nvs_keys) {
        ESP_LOGW(TAG, "No nvs_keys partition — plain NVS");
        esp_err_t ret = nvs_flash_init();
        if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
            ESP_ERROR_CHECK(nvs_flash_erase());
            ret = nvs_flash_init();
        }
        return ret;
    }

    nvs_sec_cfg_t cfg;
    esp_err_t ret = nvs_flash_read_security_cfg(nvs_keys, &cfg);
    if (ret == ESP_ERR_NVS_KEYS_NOT_INITIALIZED) {
        ret = nvs_flash_generate_keys(nvs_keys, &cfg);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "nvs_flash_generate_keys: %s", esp_err_to_name(ret));
            return ret;
        }
    } else if (ret != ESP_OK) {
        ESP_LOGE(TAG, "read_security_cfg: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = nvs_flash_secure_init(&cfg);
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_secure_init(&cfg);
    }
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "secure init failed (%s) — plain NVS", esp_err_to_name(ret));
        ret = nvs_flash_init();
        if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
            ESP_ERROR_CHECK(nvs_flash_erase());
            ret = nvs_flash_init();
        }
    } else {
        ESP_LOGI(TAG, "NVS encryption enabled");
    }
    return ret;
}
