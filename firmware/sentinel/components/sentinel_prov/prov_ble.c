#include "sentinel/prov.h"
#include "sentinel/bind_config.h"
#include "sentinel/bind_nvs.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_srp.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_wifi.h"
#include "network_provisioning/manager.h"
#include "network_provisioning/scheme_ble.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "prov";

#define PROV_SEC_NS "prov_sec"
#define SEC2_USERNAME "sentinel"
#define POP_LEN 12

static sentinel_prov_bound_cb_t s_bound_cb;
static sentinel_bind_config_t s_pending_bind;
static bool s_have_bind;
static bool s_wifi_ok;
static network_prov_security2_params_t s_sec2;
static char s_salt[32];
static char s_verifier[512];
static uint16_t s_verifier_len;

static esp_err_t load_or_create_sec2(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(PROV_SEC_NS, NVS_READONLY, &h);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = nvs_open(PROV_SEC_NS, NVS_READWRITE, &h);
        if (err != ESP_OK) {
            return err;
        }

        char pop[POP_LEN + 1];
        for (int i = 0; i < POP_LEN; i++) {
            pop[i] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"[esp_random() % 32];
        }
        pop[POP_LEN] = '\0';

        char *salt = NULL;
        char *verifier = NULL;
        int verifier_len = 0;
        err = esp_srp_gen_salt_verifier(SEC2_USERNAME, (int)strlen(SEC2_USERNAME), pop, POP_LEN,
                                        &salt, 16, &verifier, &verifier_len);
        if (err != ESP_OK) {
            nvs_close(h);
            return err;
        }

        err = nvs_set_blob(h, "salt", salt, 16);
        if (err == ESP_OK) {
            err = nvs_set_blob(h, "verifier", verifier, (size_t)verifier_len);
        }
        uint8_t shown = 0;
        if (err == ESP_OK) {
            err = nvs_set_u8(h, "pop_shown", 0);
        }
        if (err == ESP_OK) {
            err = nvs_set_str(h, "pop", pop);
        }
        if (err == ESP_OK) {
            err = nvs_commit(h);
        }

        free(salt);
        free(verifier);
        nvs_close(h);
        if (err != ESP_OK) {
            return err;
        }
        err = nvs_open(PROV_SEC_NS, NVS_READONLY, &h);
    }
    if (err != ESP_OK) {
        return err;
    }

    size_t salt_len = sizeof(s_salt);
    err = nvs_get_blob(h, "salt", s_salt, &salt_len);
    if (err != ESP_OK) {
        nvs_close(h);
        return err;
    }

    size_t vlen = sizeof(s_verifier);
    err = nvs_get_blob(h, "verifier", s_verifier, &vlen);
    if (err != ESP_OK) {
        nvs_close(h);
        return err;
    }
    s_verifier_len = (uint16_t)vlen;

    uint8_t pop_shown = 1;
    nvs_get_u8(h, "pop_shown", &pop_shown);
    if (!pop_shown) {
        char pop[POP_LEN + 1];
        size_t plen = sizeof(pop);
        if (nvs_get_str(h, "pop", pop, &plen) == ESP_OK) {
            ESP_LOGW(TAG, "=== BLE PoP (write on tape, not in git): %s ===", pop);
            ESP_LOGW(TAG, "=== Security2 username: %s ===", SEC2_USERNAME);
        }
        nvs_close(h);
        h = 0;
        if (nvs_open(PROV_SEC_NS, NVS_READWRITE, &h) == ESP_OK) {
            nvs_set_u8(h, "pop_shown", 1);
            nvs_commit(h);
            nvs_close(h);
        }
    } else {
        nvs_close(h);
    }

    s_sec2.salt = s_salt;
    s_sec2.salt_len = 16;
    s_sec2.verifier = s_verifier;
    s_sec2.verifier_len = s_verifier_len;
    return ESP_OK;
}

static void try_finalize_bind(void)
{
    if (!s_wifi_ok || !s_have_bind || !s_bound_cb) {
        return;
    }
    sentinel_bind_config_t cfg;
    sentinel_bind_phase_t phase =
        sentinel_bind_transition(SENTINEL_BIND_UNBOUND, true, true, &s_pending_bind, &cfg);
    if (phase != SENTINEL_BIND_BOUND) {
        return;
    }
    if (sentinel_bind_nvs_save(&cfg) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to persist bind NVS");
        return;
    }
    s_bound_cb(&cfg);
}

static esp_err_t bind_handler(uint32_t session_id, const uint8_t *inbuf, ssize_t inlen,
                              uint8_t **outbuf, ssize_t *outlen, void *priv_data)
{
    (void)session_id;
    (void)priv_data;
    if (!inbuf || inlen <= 0) {
        return ESP_ERR_INVALID_ARG;
    }

    sentinel_bind_parse_err_t perr =
        sentinel_bind_parse_json((const char *)inbuf, (size_t)inlen, &s_pending_bind);
    if (perr != SENTINEL_BIND_PARSE_OK) {
        ESP_LOGE(TAG, "sentinel-bind parse failed (%d)", (int)perr);
        *outbuf = (uint8_t *)strdup("ERR");
        *outlen = (*outbuf) ? 4 : 0;
        return (*outbuf) ? ESP_OK : ESP_ERR_NO_MEM;
    }
    s_have_bind = true;
    ESP_LOGI(TAG, "sentinel-bind accepted for camera_id=%s host=%s", s_pending_bind.camera_id,
             s_pending_bind.host_id);
    try_finalize_bind();

    *outbuf = (uint8_t *)strdup("OK");
    if (!*outbuf) {
        return ESP_ERR_NO_MEM;
    }
    *outlen = 3;
    return ESP_OK;
}

static void prov_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id,
                               void *event_data)
{
    (void)arg;
    if (event_base != NETWORK_PROV_EVENT) {
        return;
    }
    switch (event_id) {
    case NETWORK_PROV_WIFI_CRED_SUCCESS:
        s_wifi_ok = true;
        ESP_LOGI(TAG, "Wi-Fi provision success");
        try_finalize_bind();
        break;
    case NETWORK_PROV_WIFI_CRED_FAIL:
        ESP_LOGE(TAG, "Wi-Fi provision failed");
        break;
    case NETWORK_PROV_END:
        ESP_LOGI(TAG, "Provisioning ended");
        break;
    default:
        break;
    }
}

static void get_ble_name(char *name, size_t max)
{
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(name, max, "SENTINEL-%02X%02X", mac[4], mac[5]);
}

esp_err_t sentinel_prov_start(sentinel_prov_bound_cb_t on_bound)
{
    s_bound_cb = on_bound;
    s_have_bind = false;
    s_wifi_ok = false;

    ESP_ERROR_CHECK(esp_event_handler_register(NETWORK_PROV_EVENT, ESP_EVENT_ANY_ID,
                                               &prov_event_handler, NULL));

    network_prov_mgr_config_t config = {
        .scheme = network_prov_scheme_ble,
        .scheme_event_handler = NETWORK_PROV_SCHEME_BLE_EVENT_HANDLER_FREE_BTDM,
    };
    ESP_ERROR_CHECK(network_prov_mgr_init(config));

    bool provisioned = false;
    ESP_ERROR_CHECK(network_prov_mgr_is_wifi_provisioned(&provisioned));
    if (provisioned) {
        ESP_LOGW(TAG, "Wi-Fi already provisioned but device UNBOUND — resetting prov state");
        network_prov_mgr_reset_wifi_provisioning();
    }

    ESP_ERROR_CHECK(load_or_create_sec2());

    char service_name[16];
    get_ble_name(service_name, sizeof(service_name));

    network_prov_mgr_endpoint_create("sentinel-bind");
    ESP_ERROR_CHECK(network_prov_mgr_start_provisioning(NETWORK_PROV_SECURITY_2, &s_sec2,
                                                        service_name, NULL));
    network_prov_mgr_endpoint_register("sentinel-bind", bind_handler, NULL);

    ESP_LOGI(TAG, "BLE provisioning as %s (Security 2)", service_name);
    return ESP_OK;
}

void sentinel_prov_deinit(void)
{
    network_prov_mgr_deinit();
}
