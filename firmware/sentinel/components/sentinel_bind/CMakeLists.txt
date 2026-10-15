idf_component_register(
    SRCS "bind_parse.c" "bind_nvs.c"
    INCLUDE_DIRS "include"
    REQUIRES nvs_flash cjson
)
