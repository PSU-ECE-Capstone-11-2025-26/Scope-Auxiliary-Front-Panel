# Tuning knobs for “feel”
VERT_STEP_DIVS = 0.10  # Vertical position step per encoder detent (+/-1)
HORIZ_STEP_PCT = 1.0  # Horizontal position step in percent (0..~100) per detent

# Vertical scale: 1/2/5 sequence per Tektronix spec, index 0 = 1 V/div
# Range: index -10 (500 µV/div) to index 6 (100 V/div)
VERT_MANTISSAS = [1.0, 2.0, 5.0]
VERT_MIN_IDX = -10
VERT_MAX_IDX = 6

# Horizontal scale: 1/2/4 sequence per Tektronix spec, index 0 = 1 s/div
# Range: index -29 (200 ps/div) to index 9 (1000 s/div)
HORIZ_MANTISSAS = [1.0, 2.0, 4.0]
HORIZ_MIN_IDX = -29
HORIZ_MAX_IDX = 9

# Level encoder step size: 2/4/8 sequence
# to match the MSO, index as (vert_idx - 6) (~2% of vert scale per detent)
# e.g. 100mV/div -> 2mV/step, 200mV/div -> 4mV/step, 1V/div -> 20mV/step
LEVEL_MANTISSAS = [2.0, 4.0, 8.0]

# Zoom scale: 1/2/4 (same as horizontal)
# Range: index 0 = 1x, 1 = (2x) to index 12 (10000x)
ZOOM_MIN_IDX = 0
ZOOM_MAX_IDX = 12

GP_KNOB_FINE_SCALE = 20
GP_KNOB_COARSE_SCALE = 100
