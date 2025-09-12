# playlist_maker/core/constants.py

VERSION = "2.4.0"

# --- Configuration Defaults ---
DEFAULT_SCAN_LIBRARY = "~/music"
DEFAULT_MPD_MUSIC_DIR_CONF = "~/music"
DEFAULT_MPD_PLAYLIST_DIR_CONF = "~/.config/mpd/playlists"
DEFAULT_OUTPUT_DIR = "./playlists"
DEFAULT_MISSING_TRACKS_DIR = "./missing-tracks"
DEFAULT_LOG_FILE_NAME = "warning.log"
DEFAULT_SUPPORTED_EXTENSIONS = [".mp3", ".flac", ".ogg", ".m4a"]
DEFAULT_MATCH_THRESHOLD = 75
DEFAULT_LIVE_PENALTY_FACTOR = 0.75
DEFAULT_LIVE_ALBUM_KEYWORDS = [
    r'\blive\b', r'\bunplugged\b', r'\bconcert\b', r'live at', r'live in', r'live from',
    r'official bootleg', r'acoustic sessions', r'peel session[s]?', r'radio session[s]?',
    r'mtv unplugged'
]
DEFAULT_PARENTHETICAL_STRIP_KEYWORDS = [
    'remix', 'radio edit', 'edit', 'version', 'mix', 'acoustic',
    'mono', 'stereo', 'reprise', 'instrumental'
]
DEFAULT_OUTPUT_NAME_FORMAT = "{basename:cp}_{YYYY}-{MM}-{DD}.m3u"

DEFAULT_ENABLE_LIBRARY_CACHE = True
DEFAULT_LIBRARY_INDEX_DB_FILENAME = "library_index.sqlite" # Just the filename

# --- AI Defaults ---
DEFAULT_AI_PROVIDER = "openai" # For future expansion if other providers are added
DEFAULT_AI_MODEL = "gpt-3.5-turbo" # A common, cost-effective default

DEFAULT_SAVE_AI_SUGGESTIONS = True
DEFAULT_AI_SUGGESTIONS_LOG_DIR = "./ai-suggestions"

# --- UI and Progress Constants ---
DEFAULT_PROGRESS_UPDATE_INTERVAL = 100  # Show progress every N files
DEFAULT_AI_PROMPT_MAX_LENGTH = 50  # Maximum length for AI prompt basename
DEFAULT_GUI_ENTRY_WIDTH = 50  # Default width for GUI entry fields
DEFAULT_GUI_LOG_POLL_INTERVAL = 100  # GUI log polling interval in milliseconds
DEFAULT_GUI_SPINBOX_WIDTH = 7  # Width for GUI spinbox widgets

# --- Matching Constants ---
DEFAULT_THRESHOLD_MIN = 0  # Minimum threshold value
DEFAULT_THRESHOLD_MAX = 100  # Maximum threshold value
DEFAULT_ARTIST_BONUS_MULTIPLIER = 0.5  # Bonus multiplier for artist matches
DEFAULT_MAX_ADJUSTED_SCORE = 100.0  # Maximum adjusted score value
