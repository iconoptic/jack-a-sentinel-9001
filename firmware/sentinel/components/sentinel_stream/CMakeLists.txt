idf_component_register(
    SRCS "stream_http.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_server espressif__esp32-camera esp_timer freertos
)
