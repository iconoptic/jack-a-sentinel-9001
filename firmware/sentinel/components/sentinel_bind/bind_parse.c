#include "sentinel/bind_config.h"

#include <string.h>

#include "cJSON.h"

static bool copy_string_field(cJSON *obj, const char *key, char *dest, size_t dest_len,
                              bool required)
{
    cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsString(item) || item->valuestring == NULL) {
        return !required;
    }
    size_t n = strlen(item->valuestring);
    if (n >= dest_len) {
        return false;
    }
    memcpy(dest, item->valuestring, n + 1);
    return true;
}

sentinel_bind_parse_err_t sentinel_bind_parse_json(const char *json, size_t len,
                                                     sentinel_bind_config_t *out)
{
    if (!json || !out) {
        return SENTINEL_BIND_PARSE_INVALID_JSON;
    }
    memset(out, 0, sizeof(*out));

    cJSON *root = cJSON_ParseWithLength(json, len);
    if (!root) {
        return SENTINEL_BIND_PARSE_INVALID_JSON;
    }

    sentinel_bind_parse_err_t err = SENTINEL_BIND_PARSE_OK;
    if (!copy_string_field(root, "host_id", out->host_id, sizeof(out->host_id), true) ||
        !copy_string_field(root, "camera_id", out->camera_id, sizeof(out->camera_id), true) ||
        !copy_string_field(root, "static_ip", out->static_ip, sizeof(out->static_ip), true) ||
        !copy_string_field(root, "gateway", out->gateway, sizeof(out->gateway), true) ||
        !copy_string_field(root, "netmask", out->netmask, sizeof(out->netmask), true) ||
        !copy_string_field(root, "wifi_bssid", out->wifi_bssid, sizeof(out->wifi_bssid), true) ||
        !copy_string_field(root, "mqtt_broker", out->mqtt_broker, sizeof(out->mqtt_broker), true) ||
        !copy_string_field(root, "mqtt_username", out->mqtt_username, sizeof(out->mqtt_username),
                           true) ||
        !copy_string_field(root, "mqtt_password", out->mqtt_password, sizeof(out->mqtt_password),
                           true) ||
        !copy_string_field(root, "stream_token", out->stream_token, sizeof(out->stream_token),
                           true)) {
        err = SENTINEL_BIND_PARSE_MISSING_FIELD;
    }

    /* Optional pair; a lone SSID or PSK is a malformed payload. */
    if (err == SENTINEL_BIND_PARSE_OK) {
        if (!copy_string_field(root, "wifi_ssid", out->wifi_ssid, sizeof(out->wifi_ssid), false) ||
            !copy_string_field(root, "wifi_psk", out->wifi_psk, sizeof(out->wifi_psk), false)) {
            err = SENTINEL_BIND_PARSE_FIELD_TOO_LONG;
        } else if ((out->wifi_ssid[0] == '\0') != (out->wifi_psk[0] == '\0')) {
            err = SENTINEL_BIND_PARSE_MISSING_FIELD;
        }
    }

    cJSON *ch = cJSON_GetObjectItemCaseSensitive(root, "wifi_channel");
    if (err == SENTINEL_BIND_PARSE_OK) {
        if (!cJSON_IsNumber(ch)) {
            err = SENTINEL_BIND_PARSE_MISSING_FIELD;
        } else {
            int v = (int)cJSON_GetNumberValue(ch);
            if (v < 1 || v > 14) {
                err = SENTINEL_BIND_PARSE_MISSING_FIELD;
            } else {
                out->wifi_channel = (uint8_t)v;
            }
        }
    }

    cJSON *port = cJSON_GetObjectItemCaseSensitive(root, "mqtt_port");
    if (err == SENTINEL_BIND_PARSE_OK) {
        if (!cJSON_IsNumber(port)) {
            err = SENTINEL_BIND_PARSE_MISSING_FIELD;
        } else {
            int v = (int)cJSON_GetNumberValue(port);
            if (v <= 0 || v > 65535) {
                err = SENTINEL_BIND_PARSE_MISSING_FIELD;
            } else {
                out->mqtt_port = (uint16_t)v;
            }
        }
    }

    cJSON_Delete(root);
    return err;
}

sentinel_bind_phase_t sentinel_bind_transition(sentinel_bind_phase_t phase,
                                               bool wifi_prov_success,
                                               bool bind_payload_valid,
                                               const sentinel_bind_config_t *pending,
                                               sentinel_bind_config_t *out_config)
{
    if (phase == SENTINEL_BIND_BOUND) {
        return SENTINEL_BIND_BOUND;
    }
    if (wifi_prov_success && bind_payload_valid && pending && out_config) {
        *out_config = *pending;
        return SENTINEL_BIND_BOUND;
    }
    return SENTINEL_BIND_UNBOUND;
}
