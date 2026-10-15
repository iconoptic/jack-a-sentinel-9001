#include "sentinel/mqtt_cmd.h"

#include <string.h>

#include "cJSON.h"

sentinel_cmd_parse_err_t sentinel_mqtt_cmd_parse(const char *json, size_t len, sentinel_cmd_t *out)
{
    if (!json || !out) {
        return SENTINEL_CMD_PARSE_INVALID_JSON;
    }
    memset(out, 0, sizeof(*out));
    out->mode = SENTINEL_MODE_IDLE;

    cJSON *root = cJSON_ParseWithLength(json, len);
    if (!root) {
        return SENTINEL_CMD_PARSE_INVALID_JSON;
    }

    cJSON *mode = cJSON_GetObjectItemCaseSensitive(root, "mode");
    if (!cJSON_IsString(mode) || !mode->valuestring) {
        cJSON_Delete(root);
        return SENTINEL_CMD_PARSE_IGNORE;
    }

    if (strcmp(mode->valuestring, "idle") == 0) {
        out->mode = SENTINEL_MODE_IDLE;
    } else if (strcmp(mode->valuestring, "armed") == 0) {
        out->mode = SENTINEL_MODE_ARMED;
        cJSON *ttl = cJSON_GetObjectItemCaseSensitive(root, "ttl");
        if (cJSON_IsNumber(ttl)) {
            out->has_ttl = true;
            int v = (int)cJSON_GetNumberValue(ttl);
            out->ttl_s = (v > 0) ? (uint32_t)v : 60;
        } else {
            out->has_ttl = true;
            out->ttl_s = 60;
        }
    } else {
        cJSON_Delete(root);
        return SENTINEL_CMD_PARSE_IGNORE;
    }

    cJSON_Delete(root);
    return SENTINEL_CMD_PARSE_OK;
}

sentinel_stream_mode_t sentinel_mqtt_cmd_apply(sentinel_stream_mode_t current,
                                               const sentinel_cmd_t *cmd,
                                               int64_t now_ms,
                                               int64_t *armed_deadline_ms)
{
    if (!cmd || !armed_deadline_ms) {
        return current;
    }
    if (cmd->mode == SENTINEL_MODE_IDLE) {
        *armed_deadline_ms = 0;
        return SENTINEL_MODE_IDLE;
    }
    if (cmd->has_ttl) {
        *armed_deadline_ms = now_ms + (int64_t)cmd->ttl_s * 1000;
    } else if (*armed_deadline_ms == 0) {
        *armed_deadline_ms = now_ms + 60000;
    }
    return SENTINEL_MODE_ARMED;
}
