#include "sentinel_wifi.h"

#include <stdio.h>
#include <string.h>

#include "esp_idf_version.h"
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)
#include "esp_mac.h"
#endif

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "sentinel/bind_config.h"

static const char *TAG = "wifi";
static EventGroupHandle_t s_wifi_events;
static const int WIFI_CONNECTED_BIT = BIT0;
static uint32_t s_backoff_ms = 1000;

static void parse_mac(const char *str, uint8_t out[6])
{
    unsigned m[6];
    if (sscanf(str, "%x:%x:%x:%x:%x:%x", &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) == 6) {
        for (int i = 0; i < 6; i++) {
            out[i] = (uint8_t)m[i];
        }
    }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Disconnected — reconnect in %u ms", (unsigned)s_backoff_ms);
        vTaskDelay(pdMS_TO_TICKS(s_backoff_ms));
        if (s_backoff_ms < 60000) {
            s_backoff_ms *= 2;
        }
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_backoff_ms = 1000;
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
        ip_event_got_ip_t *event = data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}

esp_err_t sentinel_wifi_init_common(void)
{
    s_wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    return ESP_OK;
}

esp_err_t sentinel_wifi_connect_bound(const sentinel_bind_config_t *bind, const char *wifi_ssid,
                                      const char *wifi_psk)
{
    if (!bind || !wifi_ssid || !wifi_psk) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (netif) {
        esp_netif_dhcpc_stop(netif);
        esp_netif_ip_info_t ip = {0};
        esp_netif_str_to_ip4(bind->static_ip, &ip.ip);
        esp_netif_str_to_ip4(bind->gateway, &ip.gw);
        esp_netif_str_to_ip4(bind->netmask, &ip.netmask);
        ESP_ERROR_CHECK(esp_netif_set_ip_info(netif, &ip));
    }

    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, wifi_ssid, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, wifi_psk, sizeof(wc.sta.password));
    parse_mac(bind->wifi_bssid, wc.sta.bssid);
    wc.sta.bssid_set = true;
    wc.sta.channel = bind->wifi_channel;
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_connect());

    EventBits_t bits = xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE,
                                           pdMS_TO_TICKS(60000));
    return (bits & WIFI_CONNECTED_BIT) ? ESP_OK : ESP_ERR_TIMEOUT;
}

esp_err_t sentinel_wifi_wait_connected(TickType_t timeout)
{
    EventBits_t bits =
        xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, timeout);
    return (bits & WIFI_CONNECTED_BIT) ? ESP_OK : ESP_ERR_TIMEOUT;
}
