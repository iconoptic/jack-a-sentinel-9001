#pragma once

#include "esp_err.h"
#include "esp_http_server.h"

esp_err_t sentinel_stream_http_start(const char *stream_token, httpd_handle_t *out_server);
void sentinel_stream_http_stop(httpd_handle_t server);

bool sentinel_stream_check_auth(httpd_req_t *req, const char *expected_token);
