from ui.document.state.plot_layout_state import PlotType

# -- Settings files --
PROJECT_FILE_NAME = "phonlab.toml"
DISPLAY_SECTION = "display"
PLAN_KEY = "plan"
HIDDEN_TIERS_KEY = "hidden_tiers"
TIER_ORDER_KEY = "tier_order"
TIER_FONTS_KEY = "tier_fonts"

# -- Files --
PROJECT_DATABASE_FILENAME = "phonlab.db"
# Opening either of these opens the directory that holds it as a project
PROJECT_MARKER_FILES = (PROJECT_FILE_NAME, PROJECT_DATABASE_FILENAME)

# -- Mouse --
# Two clicks closer together than this are a double-click. The system's setting is
# often 500 ms, which turns a second click made to hear a selection again into a
# double-click that zooms. A single click also waits this long, in case a second
# click makes it a double-click
DOUBLE_CLICK_INTERVAL_MS = 250

# -- Document Window --
DEFAULT_WINDOW_LENGTH = 10
PLOT_ROW_SPACING = 8
PLOT_ROW_WEIGHT = {
    PlotType.WAVEFORM: 50,
    PlotType.SPECTROGRAM: 100,
    PlotType.ANNOTATION: 50,
}

# -- Document Plot --
LEFT_AXIS_WIDTH = 70

# -- Audio Editing --
MAX_UNDO_HISTORY = 10
ZERO_CROSSING_SEARCH_MS = 5

# -- Audio Player --
LATENCY_WARNING_THRESHOLD_S = 0.1
PLAYBACK_POST_ROLL_S = 0.5
PLAYBACK_FINISH_TIMEOUT_MARGIN_S = 2.0

# -- Spectrogram --
MAX_SGRAM_LENGTH = 10
DEFAULT_GRAY_CUTOFF = 0.6
SPECTROGRAM_PRE_EMPHASIS = 0.94
SPECTROGRAM_LOW_PERCENTILE = 20
SPECTROGRAM_HIGH_PERCENTILE = 80
SPECTROGRAM_PERCENTILE_SAMPLE_SIZE = 100_000
# Defaults for each spectrogram type (keyed by SpectrogramTypeState value), chosen
# when the user picks a type in the settings. The types other than fft are slow
# at a 1 ms step, so they start at 4 ms; the user can still lower it
SPECTROGRAM_WINDOW_SEC = {
    "fft": 0.008,
    "multitaper": 0.02,
    "cepstral": 0.04,
    "lpc": 0.03,
    "mel": 0.064,  # fixed by phonlab
}
SPECTROGRAM_STEP_SEC = {
    "fft": 0.001,
    "multitaper": 0.004,
    "cepstral": 0.004,
    "lpc": 0.004,
    "mel": 0.001,
}
SPECTROGRAM_MULTITAPER_NW = 3.0  # time-bandwidth product of the multitaper tapers
SPECTROGRAM_CEPSTRAL_LIFT_SEC = 0.003  # cepstral smoothing cutoff (quefrency)
PHONLAB_DOCS_URL = "https://phonlab.readthedocs.io/en/latest/"
# Documentation page of the phonlab function behind each spectrogram type
# (keyed by SpectrogramTypeState value). LPC spectra come from the coefficients
# that RLPC_formants() calculates
SPECTROGRAM_DOCS = {
    "fft": "acoustphon.html#phonlab.compute_sgram",
    "multitaper": "acoustphon.html#phonlab.compute_mt_sgram",
    "cepstral": "acoustphon.html#phonlab.cepstral_smooth",
    "lpc": "acoustphon.html#phonlab.RLPC_formants",
    "mel": "audphon.html#phonlab.compute_mel_sgram",
}
# The mel spectrogram's filters reach 7600 Hz, so it needs a top frequency of at least 8000
MEL_MIN_TOP_FREQUENCY = 8000
# Where the mel spectrogram's frequency axis is labeled (Hz)
MEL_AXIS_TICKS_HZ = (
    100,
    200,
    300,
    500,
    700,
    1000,
    1500,
    2000,
    3000,
    4000,
    5000,
    6000,
    7000,
)
# The cepstral spectrogram is analyzed this many seconds at a time to bound memory
CEPSTRAL_SEGMENT_SEC = 5

# -- Formant Tracking --
# Preemphasis each formant method works best with, by FormantMethod value
FORMANT_PREEMPHASIS = {
    "ifc": 0.94,
    "lpc": 0.94,
    "rlpc": 0.94,
    "tvlp": 0.95,
    "dppt": 0.0,
}
FORMANT_STEP_SEC = 0.01
# Analysis window length each formant method works best with. IFC has no
# window length setting, so its entry only fills the dialog's field.
FORMANT_LENGTH_SEC = {
    "ifc": 0.03,
    "lpc": 0.03,
    "rlpc": 0.03,
    "tvlp": 0.1,
    "dppt": 0.03,
}
FORMANT_VOICING_THRESHOLD = 0.5  # phon.VAD() probability to count a frame as voiced
# Documentation page of each formant method, by FormantMethod value
FORMANT_DOCS = {
    "ifc": "acoustphon.html#phonlab.IFC_formants",
    "lpc": "acoustphon.html#phonlab.LPC_formants",
    "rlpc": "acoustphon.html#phonlab.RLPC_formants",
    "tvlp": "acoustphon.html#phonlab.TVLP_formants",
    "dppt": "acoustphon.html#phonlab.DPPT_formants",
}
FORMANT_SPEAKER = 1  # 0 = long vocal tract, 1 = medium, 2 = short
FORMANT_AUTO_ORDER = -1  # let phonlab choose the LPC order
FORMANT_MIN_ORDER = 6
FORMANT_MAX_ORDER = 30
FORMANT_TOP_FREQUENCY = 6000  # RLPC and TVLP resample to twice this rate
FORMANT_MEDIAN_F0 = 200  # TVLP's expected median pitch, in Hz
FORMANT_DELTA_F = 1100  # DPPT's expected spacing between formants, in Hz
# LPC_formants always analyzes audio resampled to this rate
FORMANT_LPC_SAMPLE_RATE = 12000
# Formants are tracked a chunk at a time. Both are whole seconds, so chunks
# start on the 10 ms frame grid and on a sample at any sampling rate.
FORMANT_CHUNK_SEC = 30
FORMANT_CHUNK_OVERLAP_SEC = 1

# -- Audio Processing __
DEFAULT_FILTER_ORDER = 8

# -- Annotations --
NODE_V_MARGIN = 7
NODE_H_MARGIN = 5
POINT_LABEL_WIDTH = 100
LABEL_HEIGHT_RATIO = 0.8
# The tints that show whose tier a label is on, one for each talker in turn
TALKER_TINTS = (
    (31, 119, 180),
    (255, 127, 14),
    (44, 160, 44),
    (214, 39, 40),
    (148, 103, 189),
    (140, 86, 75),
)
# The font of annotation labels, unless the user chose another for their tier
LABEL_FONT_FAMILY = "Arial"
LABEL_FONT_SIZE = 16
SAME_NODE_PIXEL_THRESH = 7

# -- Project Import --
PROJECT_PREVIEW_ROWS = 15
PROJECT_REPORT_EXAMPLES = 8

# -- Legacy Annotation Formats --
TABLE_PREVIEW_ROWS = 12

# -- Database Inspection --
DATABASE_VIEW_ROW_LIMIT = 5000
WORD_EXAMPLE_UNMATCHED = 8  # unmatched words shown in the word table dialog

# -- Added Information (CSV files) --
INFORMATION_TOML_KEY = "information"
WORDS_TOML_KEY = "words"
