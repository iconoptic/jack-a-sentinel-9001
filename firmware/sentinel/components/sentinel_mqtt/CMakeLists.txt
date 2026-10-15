idf_component_register(
    SRCS "mqtt_cmd_parse.c" "mqtt_client.c"
    INCLUDE_DIRS "include"
    REQUIRES cjson mqtt esp_wifi esp_timer sentinel_bind sentinel_stream
)
