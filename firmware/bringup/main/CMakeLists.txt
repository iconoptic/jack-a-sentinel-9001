set(WIFI_LOCAL "${CMAKE_CURRENT_LIST_DIR}/../wifi.local")
set(WIFI_SSID "CONFIGURE_ME")
set(WIFI_PSK "CONFIGURE_ME")

if(EXISTS "${WIFI_LOCAL}")
    file(READ "${WIFI_LOCAL}" WIFI_CONTENT)
    if(WIFI_CONTENT MATCHES "SSID=([^\r\n#]+)")
        set(WIFI_SSID "${CMAKE_MATCH_1}")
    endif()
    if(WIFI_CONTENT MATCHES "PSK=([^\r\n#]+)")
        set(WIFI_PSK "${CMAKE_MATCH_1}")
    endif()
else()
    message(WARNING "wifi.local missing — copy wifi.local.example to wifi.local before flashing")
endif()

idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES nvs_flash esp_wifi esp_netif esp_event esp_http_server esp_timer driver esp32-camera
)

target_compile_definitions(${COMPONENT_LIB} PRIVATE
    WIFI_SSID=\"${WIFI_SSID}\"
    WIFI_PSK=\"${WIFI_PSK}\"
)
