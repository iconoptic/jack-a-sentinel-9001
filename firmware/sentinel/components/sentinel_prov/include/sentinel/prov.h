#pragma once

#include "esp_err.h"
#include "sentinel/bind_config.h"

typedef void (*sentinel_prov_bound_cb_t)(const sentinel_bind_config_t *cfg);

/** Start BLE Security 2 provisioning (UNBOUND). Calls cb once Wi-Fi + bind succeed. */
esp_err_t sentinel_prov_start(sentinel_prov_bound_cb_t on_bound);

/** Release provisioning manager and BT memory after bind (also called internally). */
void sentinel_prov_deinit(void);
