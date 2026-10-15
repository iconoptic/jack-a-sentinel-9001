#pragma once

#include <stdint.h>

float sentinel_stream_get_fps(void);
uint32_t sentinel_stream_get_dropped(void);
void sentinel_stream_note_drop(void);
void sentinel_stream_set_frame_interval_ms(uint32_t ms);
uint32_t sentinel_stream_get_frame_interval_ms(void);
