# playlist_maker/core/constants.py

SCRIPT_VERSION = "2.2.0" # Changed (e.g., from 2.1.0)

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