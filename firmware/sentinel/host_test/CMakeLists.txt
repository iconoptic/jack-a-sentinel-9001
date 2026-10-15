cmake_minimum_required(VERSION 3.16)
project(sentinel_host_test C)

find_package(PkgConfig REQUIRED)
pkg_check_modules(CJSON REQUIRED libcjson)

set(SENTINEL_ROOT "${CMAKE_CURRENT_LIST_DIR}/..")
add_executable(sentinel_host_test
    test_main.c
    "${SENTINEL_ROOT}/components/sentinel_bind/bind_parse.c"
    "${SENTINEL_ROOT}/components/sentinel_mqtt/mqtt_cmd_parse.c"
)
target_include_directories(sentinel_host_test PRIVATE
    "${SENTINEL_ROOT}/components/sentinel_bind/include"
    "${SENTINEL_ROOT}/components/sentinel_mqtt/include"
    ${CJSON_INCLUDE_DIRS}
)
target_link_libraries(sentinel_host_test ${CJSON_LIBRARIES})
target_compile_options(sentinel_host_test PRIVATE -Wall -Wextra)

enable_testing()
add_test(NAME sentinel_host_test COMMAND sentinel_host_test)
