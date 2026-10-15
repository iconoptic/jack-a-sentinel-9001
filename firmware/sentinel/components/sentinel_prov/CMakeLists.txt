idf_component_register(
    SRCS "prov_ble.c"
    INCLUDE_DIRS "include"
    REQUIRES network_provisioning esp_wifi nvs_flash protocomm bt sentinel_bind
)
