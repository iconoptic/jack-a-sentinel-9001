#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    SENTINEL_MODE_IDLE = 0,
    SENTINEL_MODE_ARMED,
} sentinel_stream_mode_t;

typedef enum {
    SENTINEL_CMD_PARSE_OK = 0,
    SENTINEL_CMD_PARSE_INVALID_JSON,
    SENTINEL_CMD_PARSE_UNKNOWN_MODE,
    SENTINEL_CMD_PARSE_IGNORE,
} sentinel_cmd_parse_err_t;

typedef struct {
    sentinel_stream_mode_t mode;
    bool has_ttl;
    uint32_t ttl_s;
} sentinel_cmd_t;

/** Parse CONTRACTS.md cmd JSON. Unknown fields ignored; unknown mode -> IGNORE. */
sentinel_cmd_parse_err_t sentinel_mqtt_cmd_parse(const char *json, size_t len, sentinel_cmd_t *out);

/** Apply parsed command to current mode; returns new mode and optional armed TTL deadline (monotonic ms). */
sentinel_stream_mode_t sentinel_mqtt_cmd_apply(sentinel_stream_mode_t current,
                                               const sentinel_cmd_t *cmd,
                                               int64_t now_ms,
                                               int64_t *armed_deadline_ms);
