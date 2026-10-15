#include "sentinel/mqtt_client.h"
#include "sentinel/mqtt_cmd.h"
#include "sentinel/stream_stats.h"

#include <stdio.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "nvs_flash.h"

static const char *TAG = "mqtt";

static esp_mqtt_client_handle_t s_client;
static char s_camera_id[8];
static char s_topic_state[32];
static char s_topic_telemetry[32];
static char s_topic_cmd[32];
static sentinel_stream_mode_t s_mode = SENTINEL_MODE_IDLE;
static int64_t s_armed_deadline_ms;
static sentinel_mqtt_mode_cb_t s_mode_cb;

static const char *mode_str(sentinel_stream_mode_t m)
{
    return m == SENTINEL_MODE_ARMED ? "armed" : "idle";
}

static const char *reset_reason_str(void)
{
    switch (esp_reset_reason()) {
    case ESP_RST_POWERON:
        return "poweron";
    case ESP_RST_SW:
        return "software";
    case ESP_RST_PANIC:
        return "panic";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
        return "watchdog";
    case ESP_RST_BROWNOUT:
        return "brownout";
    default:
        return "other";
    }
}

static void publish_telemetry(void)
{
    if (!s_client) {
        return;
    }

    wifi_ap_record_t ap = {0};
    int rssi = 0;
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        rssi = ap.rssi;
    }

    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"uptime_s\":%llu,\"rssi\":%d,\"heap_free\":%u,\"psram_free\":%u,"
             "\"temp_c\":%.1f,\"fps\":%.1f,\"dropped_frames\":%u,\"reset_reason\":\"%s\","
             "\"mode\":\"%s\"}",
             (unsigned long long)(esp_timer_get_time() / 1000000), rssi,
             (unsigned)esp_get_free_heap_size(),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM), 0.f, sentinel_stream_get_fps(),
             (unsigned)sentinel_stream_get_dropped(), reset_reason_str(), mode_str(s_mode));

    esp_mqtt_client_publish(s_client, s_topic_telemetry, payload, 0, 0, 0);
}

static void cmd_handler(const char *data, int len)
{
    sentinel_cmd_t cmd;
    sentinel_cmd_parse_err_t err = sentinel_mqtt_cmd_parse(data, (size_t)len, &cmd);
    if (err == SENTINEL_CMD_PARSE_IGNORE || err == SENTINEL_CMD_PARSE_INVALID_JSON) {
        return;
    }
    if (err != SENTINEL_CMD_PARSE_OK) {
        return;
    }

    int64_t now = esp_timer_get_time() / 1000;
    sentinel_stream_mode_t new_mode =
        sentinel_mqtt_cmd_apply(s_mode, &cmd, now, &s_armed_deadline_ms);
    if (new_mode != s_mode) {
        s_mode = new_mode;
        if (s_mode_cb) {
            s_mode_cb(s_mode);
        }
    } else if (s_mode == SENTINEL_MODE_ARMED && cmd.mode == SENTINEL_MODE_ARMED) {
        if (s_mode_cb) {
            s_mode_cb(s_mode);
        }
    }
}

static void mqtt_event(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    (void)handler_args;
    (void)base;
    esp_mqtt_event_handle_t event = event_data;

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT connected");
        esp_mqtt_client_publish(s_client, s_topic_state, "online", 0, 1, 0);
        publish_telemetry();
        break;
    case MQTT_EVENT_DATA:
        if (event->topic_len == (int)strlen(s_topic_cmd) &&
            strncmp(event->topic, s_topic_cmd, event->topic_len) == 0) {
            cmd_handler(event->data, event->data_len);
        }
        break;
    default:
        break;
    }
}

esp_err_t sentinel_mqtt_start(const sentinel_bind_config_t *bind, sentinel_mqtt_mode_cb_t mode_cb)
{
    if (!bind || bind->camera_id[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    s_mode_cb = mode_cb;
    strlcpy(s_camera_id, bind->camera_id, sizeof(s_camera_id));
    snprintf(s_topic_state, sizeof(s_topic_state), "sentinel/%s/state", s_camera_id);
    snprintf(s_topic_telemetry, sizeof(s_topic_telemetry), "sentinel/%s/telemetry", s_camera_id);
    snprintf(s_topic_cmd, sizeof(s_topic_cmd), "sentinel/%s/cmd", s_camera_id);

    char uri[64];
    snprintf(uri, sizeof(uri), "mqtt://%s:%u", bind->mqtt_broker, bind->mqtt_port);

    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = uri,
        .credentials.username = bind->mqtt_username,
        .credentials.authentication.password = bind->mqtt_password,
        .session.last_will.topic = s_topic_state,
        .session.last_will.msg = "offline",
        .session.last_will.qos = 1,
        .session.last_will.retain = 1,
    };

    s_client = esp_mqtt_client_init(&cfg);
    if (!s_client) {
        return ESP_FAIL;
    }
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event, NULL);
    return esp_mqtt_client_start(s_client);
}

void sentinel_mqtt_stop(void)
{
    if (s_client) {
        esp_mqtt_client_publish(s_client, s_topic_state, "offline", 0, 1, 0);
        esp_mqtt_client_stop(s_client);
        esp_mqtt_client_destroy(s_client);
        s_client = NULL;
    }
}

void sentinel_mqtt_publish_factory_reset(void)
{
    if (!s_client) {
        return;
    }
    char topic[48];
    snprintf(topic, sizeof(topic), "sentinel/%s/telemetry", s_camera_id);
    esp_mqtt_client_publish(s_client, topic, "{\"event\":\"factory_reset\"}", 0, 0, 0);
}

void sentinel_mqtt_tick(int64_t now_ms)
{
    if (s_mode == SENTINEL_MODE_ARMED && s_armed_deadline_ms > 0 && now_ms >= s_armed_deadline_ms) {
        s_mode = SENTINEL_MODE_IDLE;
        s_armed_deadline_ms = 0;
        if (s_mode_cb) {
            s_mode_cb(s_mode);
        }
    }
}

void sentinel_mqtt_telemetry_task(void *arg)
{
    (void)arg;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(30000));
        publish_telemetry();
        sentinel_mqtt_tick(esp_timer_get_time() / 1000);
    }
}

sentinel_stream_mode_t sentinel_mqtt_current_mode(void)
{
    return s_mode;
}
