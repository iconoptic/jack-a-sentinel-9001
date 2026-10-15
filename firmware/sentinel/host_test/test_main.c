#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "sentinel/bind_config.h"
#include "sentinel/mqtt_cmd.h"

static void test_bind_parse_ok(void)
{
    const char *json =
        "{"
        "\"host_id\":\"fedora-cubicle-1\","
        "\"camera_id\":\"a\","
        "\"static_ip\":\"10.77.0.11\","
        "\"gateway\":\"10.77.0.1\","
        "\"netmask\":\"255.255.255.0\","
        "\"wifi_bssid\":\"aa:bb:cc:dd:ee:ff\","
        "\"wifi_channel\":6,"
        "\"mqtt_broker\":\"10.77.0.1\","
        "\"mqtt_port\":1883,"
        "\"mqtt_username\":\"cam_a\","
        "\"mqtt_password\":\"secret\","
        "\"stream_token\":\"tok\","
        "\"mqtt_ca_pem\":\"ignored until phase 6\""
        "}";

    sentinel_bind_config_t cfg;
    assert(sentinel_bind_parse_json(json, strlen(json), &cfg) == SENTINEL_BIND_PARSE_OK);
    assert(strcmp(cfg.camera_id, "a") == 0);
    assert(cfg.wifi_channel == 6);
    assert(cfg.mqtt_port == 1883);
}

static const char *const BIND_BASE =
    "\"host_id\":\"fedora-cubicle-1\",\"camera_id\":\"b\",\"static_ip\":\"10.77.0.12\","
    "\"gateway\":\"10.77.0.1\",\"netmask\":\"255.255.255.0\","
    "\"wifi_bssid\":\"aa:bb:cc:dd:ee:ff\",\"wifi_channel\":11,"
    "\"mqtt_broker\":\"10.77.0.1\",\"mqtt_port\":1883,\"mqtt_username\":\"cam_b\","
    "\"mqtt_password\":\"secret\",\"stream_token\":\"tok\"";

static void test_bind_parse_wifi_creds(void)
{
    char json[768];
    sentinel_bind_config_t cfg;

    /* BLE-bound boards: no wifi_ssid / wifi_psk, creds live in the esp_wifi namespace. */
    snprintf(json, sizeof(json), "{%s}", BIND_BASE);
    assert(sentinel_bind_parse_json(json, strlen(json), &cfg) == SENTINEL_BIND_PARSE_OK);
    assert(cfg.wifi_ssid[0] == '\0' && cfg.wifi_psk[0] == '\0');

    /* One-click flash: both present. */
    snprintf(json, sizeof(json), "{%s,\"wifi_ssid\":\"ap3f9a1c\",\"wifi_psk\":\"0123456789abcdef\"}",
             BIND_BASE);
    assert(sentinel_bind_parse_json(json, strlen(json), &cfg) == SENTINEL_BIND_PARSE_OK);
    assert(strcmp(cfg.wifi_ssid, "ap3f9a1c") == 0);
    assert(strcmp(cfg.wifi_psk, "0123456789abcdef") == 0);

    /* A lone SSID or PSK is malformed. */
    snprintf(json, sizeof(json), "{%s,\"wifi_ssid\":\"ap3f9a1c\"}", BIND_BASE);
    assert(sentinel_bind_parse_json(json, strlen(json), &cfg) == SENTINEL_BIND_PARSE_MISSING_FIELD);
    snprintf(json, sizeof(json), "{%s,\"wifi_psk\":\"0123456789abcdef\"}", BIND_BASE);
    assert(sentinel_bind_parse_json(json, strlen(json), &cfg) == SENTINEL_BIND_PARSE_MISSING_FIELD);

    /* SSID longer than 32 bytes does not fit. */
    snprintf(json, sizeof(json),
             "{%s,\"wifi_ssid\":\"%s\",\"wifi_psk\":\"0123456789abcdef\"}", BIND_BASE,
             "0123456789012345678901234567890123");
    assert(sentinel_bind_parse_json(json, strlen(json), &cfg) == SENTINEL_BIND_PARSE_FIELD_TOO_LONG);
}

static void test_bind_transition(void)
{
    sentinel_bind_config_t pending = {0};
    strncpy(pending.camera_id, "a", sizeof(pending.camera_id) - 1);
    sentinel_bind_config_t out = {0};

    assert(sentinel_bind_transition(SENTINEL_BIND_UNBOUND, false, true, &pending, &out) ==
           SENTINEL_BIND_UNBOUND);
    assert(sentinel_bind_transition(SENTINEL_BIND_UNBOUND, true, true, &pending, &out) ==
           SENTINEL_BIND_BOUND);
    assert(strcmp(out.camera_id, "a") == 0);
}

static void test_cmd_armed_ttl(void)
{
    const char *json = "{\"mode\":\"armed\",\"ttl\":60}";
    sentinel_cmd_t cmd;
    assert(sentinel_mqtt_cmd_parse(json, strlen(json), &cmd) == SENTINEL_CMD_PARSE_OK);
    int64_t deadline = 0;
    assert(sentinel_mqtt_cmd_apply(SENTINEL_MODE_IDLE, &cmd, 1000, &deadline) ==
           SENTINEL_MODE_ARMED);
    assert(deadline == 61000);
}

static void test_cmd_unknown_mode(void)
{
    const char *json = "{\"mode\":\"turbo\"}";
    sentinel_cmd_t cmd;
    assert(sentinel_mqtt_cmd_parse(json, strlen(json), &cmd) == SENTINEL_CMD_PARSE_IGNORE);
}

int main(void)
{
    test_bind_parse_ok();
    test_bind_parse_wifi_creds();
    test_bind_transition();
    test_cmd_armed_ttl();
    test_cmd_unknown_mode();
    puts("sentinel_host_test: OK");
    return 0;
}
