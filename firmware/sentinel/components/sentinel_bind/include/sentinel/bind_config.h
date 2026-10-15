#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SENTINEL_BIND_NS          "bind"
#define SENTINEL_BIND_KEY_BOUND   "bound"
#define SENTINEL_EXPECTED_SENSOR_PID 0x3660

#define SENTINEL_HOST_ID_MAX      64
#define SENTINEL_CAMERA_ID_MAX    8
#define SENTINEL_IP_STR_MAX       16
#define SENTINEL_BSSID_STR_MAX    18
#define SENTINEL_MQTT_USER_MAX    32
#define SENTINEL_MQTT_PASS_MAX    128
#define SENTINEL_STREAM_TOKEN_MAX 128
#define SENTINEL_WIFI_SSID_MAX    33  /* 32 + NUL */
#define SENTINEL_WIFI_PSK_MAX     65  /* 63 + NUL */

typedef enum {
    SENTINEL_BIND_UNBOUND = 0,
    SENTINEL_BIND_BOUND = 1,
} sentinel_bind_phase_t;

typedef struct {
    char host_id[SENTINEL_HOST_ID_MAX];
    char camera_id[SENTINEL_CAMERA_ID_MAX];
    char static_ip[SENTINEL_IP_STR_MAX];
    char gateway[SENTINEL_IP_STR_MAX];
    char netmask[SENTINEL_IP_STR_MAX];
    char wifi_bssid[SENTINEL_BSSID_STR_MAX];
    uint8_t wifi_channel;
    char mqtt_broker[SENTINEL_IP_STR_MAX];
    uint16_t mqtt_port;
    char mqtt_username[SENTINEL_MQTT_USER_MAX];
    char mqtt_password[SENTINEL_MQTT_PASS_MAX];
    char stream_token[SENTINEL_STREAM_TOKEN_MAX];
    /**
     * Optional. Set by the one-click flasher (scripts/install-esp32.sh) so the board boots
     * BOUND with no BLE step. Empty for BLE-bound boards, which keep the SSID/PSK that
     * network_provisioning stored in the esp_wifi NVS namespace.
     */
    char wifi_ssid[SENTINEL_WIFI_SSID_MAX];
    char wifi_psk[SENTINEL_WIFI_PSK_MAX];
} sentinel_bind_config_t;

typedef enum {
    SENTINEL_BIND_PARSE_OK = 0,
    SENTINEL_BIND_PARSE_INVALID_JSON,
    SENTINEL_BIND_PARSE_MISSING_FIELD,
    SENTINEL_BIND_PARSE_FIELD_TOO_LONG,
} sentinel_bind_parse_err_t;

/** Parse CONTRACTS.md sentinel-bind JSON. Ignores unknown fields (e.g. mqtt_ca_pem).
 *  Optional: wifi_ssid, wifi_psk (both or neither). */
sentinel_bind_parse_err_t sentinel_bind_parse_json(const char *json, size_t len,
                                                     sentinel_bind_config_t *out);

/**
 * Bind state machine transitions (pure logic for unit tests).
 * Returns new phase; *out_config updated when entering BOUND.
 */
sentinel_bind_phase_t sentinel_bind_transition(sentinel_bind_phase_t phase,
                                               bool wifi_prov_success,
                                               bool bind_payload_valid,
                                               const sentinel_bind_config_t *pending,
                                               sentinel_bind_config_t *out_config);
