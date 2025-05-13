#!/usr/bin/env python3
import os
import sys
import mutagen
import mutagen.mp3
import mutagen.flac
import mutagen.oggvorbis
import mutagen.mp4
from pathlib import Path
from fuzzywuzzy import fuzz
import logging
import argparse
import time
import unicodedata
import re
from datetime import datetime
import random # Needed for interactive random choice
import configparser # For reading config files
try:
    import pandas as pd
    # Logging for this debug message will only appear if main() later sets DEBUG level
    logging.debug("Pandas library found and imported for __main__ block.")
except ImportError:
    class DummyPandas:
        def isna(self, val):
            if val is None: return True
            try: return val != val # NaN comparison trick
            except TypeError: return False # Not comparable, not NaN
    pd = DummyPandas()
    # Log this at INFO because it's a noticeable fallback
    # Will appear if main() sets INFO or DEBUG
    logging.info("Pandas library not found for __main__ block; using basic duration checks.")

# --- Configuration Defaults & Script Info ---
SCRIPT_VERSION = "1.7.0" # Or whatever you decide your starting version is

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

# --- ANSI Color Codes ---
_IS_TTY = sys.stdout.isatty() # Basic check if we're likely in a TTY

class Colors:
    RESET = "\033[0m" if _IS_TTY else ""
    RED = "\033[91m" if _IS_TTY else ""
    GREEN = "\033[92m" if _IS_TTY else ""
    YELLOW = "\033[93m" if _IS_TTY else ""
    BLUE = "\033[94m" if _IS_TTY else ""
    MAGENTA = "\033[95m" if _IS_TTY else ""
    CYAN = "\033[96m" if _IS_TTY else ""
    BOLD = "\033[1m" if _IS_TTY else ""
    UNDERLINE = "\033[4m" if _IS_TTY else ""

def colorize(text, color_code):
    """Wraps text with ANSI color codes, if supported."""
    return f"{color_code}{text}{Colors.RESET}"

# --- Global Variables ---
library_index = []
INTERACTIVE_MODE = False # Set in main() based on config/args
PARENTHETICAL_STRIP_REGEX = None # Compiled in main()

# --- Configuration File Handling ---
CONFIG_FILENAME_LOCAL = "playlist_maker.conf"
CONFIG_FILENAME_USER = "config.ini"
CONFIG_DIR_USER = Path.home() / ".config" / "playlist-maker"

# Initialize config parser with a list converter
def parse_list(value):
    # Split by comma or whitespace, filter empty strings
    return [item.strip() for item in re.split(r'[,\s]+', value) if item.strip()]

config = configparser.ConfigParser(
    interpolation=None,
    converters={'list': parse_list}
)

# --- Config Helper Function ---
def get_config(section, option, fallback=None, expected_type=str):
    """
    Retrieves a value from the loaded configparser object. Handles type conversion and fallbacks.
    Uses the globally defined 'config' object.
    """
    value = None
    raw_value_for_log = "N/A" # For logging errors
    try:
        if expected_type == bool:
            value = config.getboolean(section, option)
        elif expected_type == int:
            value = config.getint(section, option)
        elif expected_type == float:
            value = config.getfloat(section, option)
        elif expected_type == list:
            value = config.getlist(section, option) # Uses the custom converter
        else: # Default to string
             value = config.get(section, option, fallback=None) # Internal fallback None
             # Explicitly handle case where option exists but has no value -> treat as fallback
             if value == "":
                 logging.debug(f"Config: [{section}] {option} is empty. Using fallback: {fallback}")
                 return fallback
             elif value is None:
                 return fallback # If config.get returns None itself

        # If we got a value successfully
        return value

    except (configparser.NoSectionError, configparser.NoOptionError):
        # logging.debug(f"Config: [{section}] {option} not found. Using fallback: {fallback}")
        return fallback
    except ValueError as e:
        # Log error during conversion
        try:
            raw_value_for_log = config.get(section, option, raw=True)
        except:
            raw_value_for_log = "[Could not retrieve raw value]"
        logging.warning(f"Config Error: Invalid value for [{section}] {option} = '{raw_value_for_log}'. "
                        f"Could not convert to {expected_type.__name__}. Using fallback: {fallback}. Error: {e}")
        return fallback
    except Exception as e:
        # Catch unexpected errors during config reading
        logging.error(f"Config Error: Unexpected error reading [{section}] {option}. "
                      f"Using fallback: {fallback}. Error: {e}", exc_info=True)
        return fallback

# --- Normalization Functions ---
def normalize_and_detect_specific_live_format(s):
    """
    Normalizes a string for matching (handling '&', '/', 'and', feat., common suffixes in parens)
    and specifically detects if it contains '(live)' format in the original casing structure.
    Returns normalized string for matching and a boolean for live detection.
    Uses global PARENTHETICAL_STRIP_REGEX.
    """
    global PARENTHETICAL_STRIP_REGEX

    if not isinstance(s, str): return "", False

    original_s_lower_for_live_check = s.lower()

    is_live_format = bool(re.search(r'\(\s*live[\s\W]*\)', original_s_lower_for_live_check, re.IGNORECASE))

    try:
        normalized_s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    except TypeError:
        logging.warning(f"Normalization failed for non-string input: {s}")
        return "", False

    s_for_matching = normalized_s.lower()
    logging.debug(f"Norm Step 1 (Input='{s}'): NFD+Lower='{s_for_matching}' | LiveFormatDetected={is_live_format}")

    s_for_matching = re.sub(r'\s*&\s*', ' ', s_for_matching)
    s_for_matching = re.sub(r'\s*/\s*', ' ', s_for_matching)
    s_for_matching = re.sub(r'\s+and\s+', ' ', s_for_matching)
    logging.debug(f"Norm Step 2: Replace '&/and' -> '{s_for_matching}'")

    s_for_matching = re.sub(r'^\s*\d{1,3}[\s.-]+\s*', '', s_for_matching).strip()
    logging.debug(f"Norm Step 3: Strip TrackNum -> '{s_for_matching}'")

    def process_parenthetical_content(match):
        content = match.group(1).strip().lower()
        logging.debug(f"Norm Step 4a: Examining Parenthesis Content: '{content}'")

        if re.fullmatch(r'live[\s\W]*', content, re.IGNORECASE):
            logging.debug(f"  -> Keeping 'live' token.")
            return ' live '

        feat_match = re.match(r'(?:feat|ft|featuring|with)\.?\s*(.*)', content, re.IGNORECASE)
        if feat_match:
            feat_artist = feat_match.group(1).strip()
            feat_artist_norm = ''.join(c for c in feat_artist if c.isalnum() or c.isspace())
            feat_artist_norm = re.sub(r'\s+', ' ', feat_artist_norm).strip()
            logging.debug(f"  -> Keeping 'feat' token with normalized artist: 'feat {feat_artist_norm}'")
            return f' feat {feat_artist_norm} '

        # Use the pre-compiled regex (check if it exists)
        if PARENTHETICAL_STRIP_REGEX and PARENTHETICAL_STRIP_REGEX.search(content): # Use search, maybe not fullmatch
             logging.debug(f"  -> Removing common suffix/term found in parenthesis: '{content}' matched by {PARENTHETICAL_STRIP_REGEX.pattern}")
             return ''

        logging.debug(f"  -> Removing generic parenthesis content.")
        return ''

    s_for_matching = re.sub(r'\(([^)]*)\)', process_parenthetical_content, s_for_matching)
    logging.debug(f"Norm Step 4b: After Parenthesis Processing -> '{s_for_matching}'")

    s_for_matching = ''.join(c for c in s_for_matching if c.isalnum() or c.isspace())
    s_for_matching = re.sub(r'\s+', ' ', s_for_matching).strip()
    logging.debug(f"Norm Step 5 (Final): String='{s_for_matching}' | LiveDetected={is_live_format}")

    return s_for_matching, is_live_format

def normalize_string_for_matching(s):
    """Just returns the normalized string part for general matching."""
    stripped_s, _ = normalize_and_detect_specific_live_format(s)
    return stripped_s

def check_album_for_live_indicators(album_title_str, live_keywords_regex):
    """ Checks album title using standard normalization and regex/specific format. """
    if not isinstance(album_title_str, str) or not album_title_str:
        return False

    normalized_album_for_check, album_has_specific_live_format = normalize_and_detect_specific_live_format(album_title_str)

    if live_keywords_regex and live_keywords_regex.search(normalized_album_for_check):
        logging.debug(f"Album '{album_title_str}' (normalized: '{normalized_album_for_check}') matched live indicator regex.")
        return True

    if album_has_specific_live_format:
        logging.debug(f"Album '{album_title_str}' detected specific '(live)' format during normalization.")
        return True

    return False

# --- Logging Setup ---
def setup_logging(log_file_path, log_mode):
    """Configures logging to file and console."""
    filemode = 'a' if log_mode == 'append' else 'w'
    log_file_str = ""
    try:
        # Ensure the parent directory exists
        log_parent_dir = log_file_path.parent
        log_parent_dir.mkdir(parents=True, exist_ok=True)
        log_file_str = str(log_file_path)
        # Check write permissions early
        if not os.access(log_parent_dir, os.W_OK):
             raise PermissionError(f"No write permission for log directory: {log_parent_dir}")
    except (PermissionError, OSError, Exception) as e:
        print(colorize(f"Error preparing log file path {log_file_path}: {e}", Colors.RED), file=sys.stderr)
        try:
            fallback_path = Path.cwd() / log_file_path.name
            log_file_str = str(fallback_path)
            print(colorize(f"Attempting to log to fallback path: {log_file_str}", Colors.YELLOW), file=sys.stderr)
            if not os.access(Path(log_file_str).parent, os.W_OK):
                 print(colorize(f"ERROR: No write permission for fallback log directory either: {Path(log_file_str).parent}", Colors.RED), file=sys.stderr)
                 return # Cannot log anywhere
        except Exception as fallback_e:
             print(colorize(f"ERROR: Could not determine fallback log path: {fallback_e}", Colors.RED), file=sys.stderr)
             return # Critical logging failure

    # Remove existing handlers to avoid duplicates if re-run in same session
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        handler.close() # Close file handles if any

    try:
        # File Handler (level set later in main)
        logging.basicConfig(
            level=logging.DEBUG, # Set lowest level here, control filtering via logger level later
            format="%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s",
            filename=log_file_str,
            filemode=filemode,
            force=True # Overwrite basicConfig if called multiple times
        )
        # Console Handler (fixed at WARNING level for user feedback)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        formatter = logging.Formatter(f'{Colors.YELLOW}%(levelname)s:{Colors.RESET} [%(funcName)s] %(message)s')
        console_handler.setFormatter(formatter)
        logger = logging.getLogger()
        # Ensure only one console handler to stderr is added
        if not any(isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers):
             logger.addHandler(console_handler)

    except Exception as e:
         print(colorize(f"ERROR: Exception during logging setup: {e}", Colors.RED), file=sys.stderr)

# --- Metadata Reading ---
def get_file_metadata(file_path_obj):
    """Extracts Artist, Title, Album, Duration from an audio file."""
    artist, title, album, duration = "", "", "", None
    try:
        # Use easy=True for common tags, but fallback to detailed for duration
        audio = mutagen.File(file_path_obj, easy=True)
        detailed_audio = mutagen.File(file_path_obj) # Open again for detailed info

        if audio:
            artist_tags = audio.get("artist", []) or audio.get("albumartist", []) or audio.get("performer", [])
            artist = artist_tags[0].strip() if artist_tags else ""
            title_tags = audio.get("title", [])
            title = title_tags[0].strip() if title_tags else ""
            album_tags = audio.get("album", [])
            album = album_tags[0].strip() if album_tags else ""

        if detailed_audio and hasattr(detailed_audio, 'info') and hasattr(detailed_audio.info, 'length'):
            try:
                duration_float = float(detailed_audio.info.length)
                if not pd.isna(duration_float): # Use dummy if pandas not installed
                    duration = int(duration_float)
            except (ValueError, TypeError):
                duration = None # Keep duration None if conversion fails

        if duration is None and hasattr(detailed_audio, 'info') and hasattr(detailed_audio.info, 'length'):
            logging.debug(f"Metadata: Non-numeric duration for {file_path_obj} (info.length: {detailed_audio.info.length})")
        elif duration is None:
             logging.debug(f"Metadata: Could not determine duration for {file_path_obj}")

        if not artist and audio: logging.debug(f"Metadata: Artist tag missing for {file_path_obj}")
        if not title and audio: logging.debug(f"Metadata: Title tag missing for {file_path_obj}")

    except mutagen.MutagenError as me:
        logging.debug(f"Mutagen specific error reading {file_path_obj}: {me}")
    except Exception as e:
        logging.warning(f"Could not read metadata for {file_path_obj} due to {type(e).__name__}: {e}", exc_info=False)
        artist, title, album, duration = artist or "", title or "", album or "", duration or None # Ensure defaults on error

    return artist, title, album, duration

import re
from datetime import datetime
import os # For os.path.splitext
import logging # Assuming logging is configured

# Make sure this function is defined in your playlist_maker.py

def format_output_filename(format_string, raw_basename, now, default_extension=".m3u"):
    """
    Formats the output filename based on a format string, raw basename, and current time.
    """
    if format_string is None: # Use default logic if no format string is provided
        sanitized_base = re.sub(r'[^a-zA-Z0-9]+', '_', raw_basename).strip('_')
        date_str = now.strftime("%Y-%m-%d")
        filename_stem = f"{sanitized_base}_{date_str}" if sanitized_base else f"playlist_{date_str}"
        return f"{filename_stem}{default_extension}"

    # --- Helper for {basename:transforms} ---
    def process_basename(current_basename, transform_codes_str):
        processed_name = current_basename
        transformed_separator = False # Flag to ensure only one separator transform is applied

        # 1. Separator Transformations (order of precedence: p, then s, then _)
        if 'p' in transform_codes_str: # Spacify: Convert common separators to space
            processed_name = re.sub(r'[-_.]+', ' ', processed_name)
            processed_name = re.sub(r'\s+', ' ', processed_name).strip() # Consolidate spaces
            transformed_separator = True
        elif 's' in transform_codes_str and not transformed_separator: # Hyphenate
            processed_name = re.sub(r'[\s_.]+', '-', processed_name) # Spaces, underscores, dots to hyphen
            processed_name = re.sub(r'-+', '-', processed_name).strip('-') # Consolidate hyphens
            transformed_separator = True
        elif '_' in transform_codes_str and not transformed_separator: # Underscorify
            processed_name = re.sub(r'[\s-.]+', '_', processed_name) # Spaces, hyphens, dots to underscore
            processed_name = re.sub(r'_+', '_', processed_name).strip('_') # Consolidate underscores
            transformed_separator = True
        
        transformed_case = False # Flag to ensure only one case transform is applied
        # 2. Case Transformations (order of precedence: c, then u, then l)
        #    Operates on the (potentially separator-transformed) name
        if 'c' in transform_codes_str: # Capitalize words
            # Split by space, capitalize, then join. Handles multiple spaces if they exist after sep transform.
            processed_name = ' '.join(word.capitalize() for word in processed_name.split(' ') if word) # Avoid empty strings from multiple spaces
            transformed_case = True
        elif 'u' in transform_codes_str and not transformed_case: # Uppercase
            processed_name = processed_name.upper()
            transformed_case = True
        elif 'l' in transform_codes_str and not transformed_case: # Lowercase
            processed_name = processed_name.lower()
            transformed_case = True
            
        return processed_name

    # --- Apply transformations ---
    final_filename_str = format_string

    # Substitute {basename:transforms} or {basename}
    def basename_replacer(match):
        # match.group(1) will contain the transform codes like "cp",
        # or an empty string if no codes are specified (e.g., "{basename}" or "{basename:}").
        transform_codes = match.group(1) 
        return process_basename(raw_basename, transform_codes)
    
    # This regex matches "{basename}", optionally followed by a colon, 
    # and then captures the transform codes (possibly empty) into group 1.
    final_filename_str = re.sub(r'\{basename:?([culps_]*)\}', basename_replacer, final_filename_str)

    # Substitute date/time placeholders like {YYYY}, {MM}, etc.
    dt_replacements = {
        'YYYY': now.strftime("%Y"), 'YY': now.strftime("%y"),
        'MM': now.strftime("%m"), 'DD': now.strftime("%d"),
        'hh': now.strftime("%H"), 'mm': now.strftime("%M"),
        'ss': now.strftime("%S"),
    }
    for key, value in dt_replacements.items():
        final_filename_str = final_filename_str.replace(f"{{{key}}}", value)

    # --- Final Sanitization and Extension Handling ---
    name_part, current_extension = os.path.splitext(final_filename_str)
    
    if not current_extension.strip() or current_extension.strip() == ".":
        current_extension = default_extension
    
    invalid_fs_chars_regex = r'[\\/:*?"<>|\x00-\x1F\x7F]'
    sanitized_name_part = re.sub(invalid_fs_chars_regex, '_', name_part)
    sanitized_name_part = re.sub(r'_+', '_', sanitized_name_part) # Consolidate multiple underscores
    sanitized_name_part = sanitized_name_part.strip('_. ') # Remove leading/trailing problematic chars

    if not sanitized_name_part:
        logging.warning(
            f"Generated filename format ('{format_string}') for basename ('{raw_basename}') "
            f"resulted in an empty/invalid stem ('{name_part}' -> '{sanitized_name_part}'). Falling back to default naming."
        )
        sanitized_base_fallback = re.sub(r'[^a-zA-Z0-9]+', '_', raw_basename).strip('_')
        date_str_fallback = now.strftime("%Y-%m-%d")
        filename_stem_fallback = f"{sanitized_base_fallback}_{date_str_fallback}" if sanitized_base_fallback else f"playlist_{date_str_fallback}"
        return f"{filename_stem_fallback}{default_extension}"

    return f"{sanitized_name_part}{current_extension}"

    # --- Apply transformations ---
    final_filename_str = format_string

    # Substitute {basename:transforms} or {basename}
    def basename_replacer(match):
        # group(1) is 'basename', group(2) is the optional transform codes
        transform_codes = match.group(2) if match.group(2) else ""
        return process_basename(raw_basename, transform_codes)
    final_filename_str = re.sub(r'\{basename:?([culps_]*)\}', basename_replacer, final_filename_str)

    # Substitute date/time placeholders like {YYYY}, {MM}, etc.
    dt_replacements = {
        'YYYY': now.strftime("%Y"), 'YY': now.strftime("%y"),
        'MM': now.strftime("%m"), 'DD': now.strftime("%d"),
        'hh': now.strftime("%H"), 'mm': now.strftime("%M"),
        'ss': now.strftime("%S"),
    }
    for key, value in dt_replacements.items():
        final_filename_str = final_filename_str.replace(f"{{{key}}}", value)

    # --- Final Sanitization and Extension Handling ---
    name_part, current_extension = os.path.splitext(final_filename_str)
    
    # Use default_extension if format string didn't specify one, or if specified is empty
    if not current_extension.strip() or current_extension.strip() == ".":
        current_extension = default_extension
    
    # Sanitize the name_part: remove invalid FS characters.
    # We allow spaces, hyphens, underscores, and dots (if not leading/trailing problematically).
    invalid_fs_chars_regex = r'[\\/:*?"<>|\x00-\x1F\x7F]' # Includes control chars
    sanitized_name_part = re.sub(invalid_fs_chars_regex, '_', name_part)
    
    # Consolidate multiple underscores that might result from substitution
    sanitized_name_part = re.sub(r'_+', '_', sanitized_name_part)
    
    # Remove leading/trailing problematic characters for file names
    sanitized_name_part = sanitized_name_part.strip('_. ') 

    if not sanitized_name_part: # If sanitization results in empty string
        logging.warning(
            f"Generated filename format ('{format_string}') for basename ('{raw_basename}') "
            f"resulted in an empty/invalid stem ('{name_part}' -> '{sanitized_name_part}'). Falling back to default naming."
        )
        # Fallback to a simplified default to ensure a name
        sanitized_base_fallback = re.sub(r'[^a-zA-Z0-9]+', '_', raw_basename).strip('_')
        date_str_fallback = now.strftime("%Y-%m-%d")
        filename_stem = f"{sanitized_base_fallback}_{date_str_fallback}" if sanitized_base_fallback else f"playlist_{date_str_fallback}"
        return f"{filename_stem}{default_extension}"

    return f"{sanitized_name_part}{current_extension}"

# --- Library Scanning ---
def scan_library(scan_library_path_str, supported_extensions, live_album_keywords_regex):
    """Scans the library path, extracts metadata, normalizes, and builds the index."""
    global library_index
    library_index = []
    try:
        scan_library_path = Path(scan_library_path_str).resolve(strict=True)
    except FileNotFoundError:
        logging.error(f"Scan library path does not exist: {scan_library_path_str}")
        print(colorize(f"Error: Scan library path does not exist: {scan_library_path_str}", Colors.RED), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error resolving scan library path {scan_library_path_str}: {e}")
        print(colorize(f"Error: Could not resolve scan library path {scan_library_path_str}: {e}", Colors.RED), file=sys.stderr)
        sys.exit(1)

    print(f"Scanning music library at {scan_library_path}..."); logging.info(f"Starting library scan at {scan_library_path}")
    start_time = time.time()
    processed_count = 0
    scan_errors = 0

    for root, _, files in os.walk(scan_library_path, followlinks=True):
        root_path = Path(root)
        for file in files:
            # Check extension using the provided tuple
            if file.lower().endswith(supported_extensions):
                processed_count += 1
                if processed_count % 500 == 0: print(".", end="", flush=True)

                file_path = root_path / file
                try:
                    if not os.access(file_path, os.R_OK):
                        logging.warning(f"Skipping inaccessible file during scan: {file_path}")
                        scan_errors += 1
                        continue

                    abs_file_path = file_path.resolve()
                    meta_artist, meta_title, meta_album, meta_duration = get_file_metadata(abs_file_path)

                    norm_title_match_str, title_has_live_format = normalize_and_detect_specific_live_format(meta_title)
                    norm_artist_match_str, _ = normalize_and_detect_specific_live_format(meta_artist)
                    norm_filename_match_str, filename_has_live_format = normalize_and_detect_specific_live_format(file_path.stem)

                    album_indicates_live = check_album_for_live_indicators(meta_album, live_album_keywords_regex)
                    current_entry_is_live = title_has_live_format or filename_has_live_format or album_indicates_live

                    if meta_album and album_indicates_live and not (title_has_live_format or filename_has_live_format) :
                        logging.debug(f"Track '{meta_title}' on album '{meta_album}' marked as LIVE due to album keywords. Path: {abs_file_path}")

                    library_index.append({
                        "path": str(abs_file_path),
                        "artist": meta_artist, "title": meta_title, "album": meta_album,
                        "duration": meta_duration if meta_duration is not None else -1,
                        "filename_stem": file_path.stem,
                        "norm_artist_stripped": norm_artist_match_str,
                        "norm_title_stripped": norm_title_match_str,
                        "norm_filename_stripped": norm_filename_match_str,
                        "entry_is_live": current_entry_is_live
                    })
                except OSError as e:
                    logging.warning(f"OS error processing file during scan {file_path}: {e}. Skipping.")
                    scan_errors += 1
                except Exception as e:
                    logging.error(f"Unexpected error processing file during scan {file_path}: {e}", exc_info=True)
                    scan_errors += 1

    print("\nScan complete.")
    end_time = time.time()
    logging.info(f"Library scan finished. Found {len(library_index)} tracks in {end_time - start_time:.2f} seconds.")
    if scan_errors > 0:
        logging.warning(f"Encountered {scan_errors} errors during scan (check log for details).")
        print(colorize(f"Warning: Encountered {scan_errors} errors during scan (check log).", Colors.YELLOW))
    if not library_index:
        logging.error("Library scan resulted in 0 recognized tracks.")
        print(colorize("Error: No tracks found in the specified scan library.", Colors.RED), file=sys.stderr)
        # Consider exiting if scan fails completely? No, maybe user wants to retry later.

# (Add this new function to playlist_maker.py)

def prompt_album_selection_or_skip(input_artist, input_track, artist_library_entries, input_live_format, threshold):
    """
    Prompts user to select a track from one of the input artist's albums
    when no direct track match was found.
    artist_library_entries: list of all tracks by this artist found in the library.
    """
    global library_index # Needed to list tracks from the chosen album

    print("-" * 70)
    print(f"{Colors.BOLD}{Colors.CYAN}INTERACTIVE ALBUM SELECTION for:{Colors.RESET}")
    print(f"  Input: {colorize(input_artist, Colors.BOLD)} - {colorize(input_track, Colors.BOLD)}")
    print(f"  (No direct match found for this track)")
    print("-" * 70)

    # 1. Gather unique albums for the given artist from their library entries
    # Normalize artist name from library entries for consistent matching with input_artist's norm
    # We need to be careful if input_artist was 'Various Artists' and artist_library_entries reflect that.
    # For simplicity, let's assume artist_library_entries are primarily for the *specific* input_artist.
    
    # Use normalized input artist string for more reliable filtering.
    norm_input_artist, _ = normalize_and_detect_specific_live_format(input_artist)

    # Extract unique albums (case-insensitive for album title grouping)
    # We only care about albums that actually exist in artist_library_entries
    albums_by_artist = {} # { "normalized_album_title": "Original Album Title String" }
    for entry in artist_library_entries:
        # Ensure the entry's artist is indeed a close match to the input artist
        # (this should already be true if candidate_artist_entries was formed correctly)
        lib_artist_norm = entry.get("norm_artist_stripped", "")
        if norm_input_artist in lib_artist_norm or fuzz.ratio(norm_input_artist, lib_artist_norm) > 80: # Heuristic
            album_title = entry.get("album")
            if album_title:
                norm_album = album_title.lower() # Simple normalization for grouping
                if norm_album not in albums_by_artist:
                    albums_by_artist[norm_album] = album_title # Store original casing

    if not albums_by_artist:
        print(colorize(f"No albums found in the library for artist '{input_artist}' to select from.", Colors.YELLOW))
        # Fallback to the standard skip/random prompt
        return prompt_user_for_choice(input_artist, input_track, [], artist_library_entries, input_live_format, threshold)

    # 2. Prompt user to choose an album
    while True: # Album selection loop
        print(f"\n{Colors.UNDERLINE}Artist '{input_artist}' has the following albums in your library:{Colors.RESET}")
        album_choices_map = {}
        idx = 1
        # Sort albums by their original title for display
        sorted_original_album_titles = sorted(list(albums_by_artist.values()))

        for original_album_title in sorted_original_album_titles:
            print(f"  {colorize(f'[{idx}]', Colors.BLUE)} {original_album_title}")
            album_choices_map[str(idx)] = original_album_title
            idx += 1
        
        print(f"  {colorize('[S]', Colors.RED)}kip this track input")
        album_choices_map['s'] = 'skip'
        if artist_library_entries: # Offer random only if we have artist entries
             print(f"  {colorize('[R]', Colors.YELLOW)}andom track by '{input_artist}' (from any album)")
             album_choices_map['r'] = 'random'


        try:
            album_prompt_text = colorize("Choose an album (number, S, R): ", Colors.BLUE + Colors.BOLD)
            album_choice_str = input(album_prompt_text).lower().strip()

            if album_choice_str in album_choices_map:
                selected_album_action = album_choices_map[album_choice_str]

                if selected_album_action == 'skip':
                    print(f"\n{colorize('Skipping track.', Colors.RED)}")
                    logging.info(f"INTERACTIVE (Album Select): User chose [S]kip for '{input_artist} - {input_track}'.")
                    return None
                elif selected_album_action == 'random':
                    if artist_library_entries:
                        random_entry = random.choice(artist_library_entries)
                        print(f"\n{colorize('Selected Random Track:', Colors.YELLOW + Colors.BOLD)}")
                        print(f"  Artist: {random_entry['artist']} - Title: {random_entry['title']} (Album: {random_entry.get('album', 'N/A')})")
                        logging.info(f"INTERACTIVE (Album Select): User chose [R]andom track for '{input_artist} - {input_track}'. Selected: {random_entry['path']}")
                        return random_entry
                    else: # Should not happen if 'R' is offered
                        print(colorize("Error: No tracks available for random selection by this artist.", Colors.RED))
                        continue

                # User selected an album by number
                chosen_album_title_original = selected_album_action # This is the original case album title
                logging.info(f"INTERACTIVE (Album Select): User selected album '{chosen_album_title_original}' for '{input_artist} - {input_track}'.")

                # 3. List tracks from the chosen album for that artist
                tracks_on_selected_album = []
                for lib_entry in library_index: # Iterate through the whole library
                    # Match artist (normalized) and album (original case)
                    lib_artist_norm = lib_entry.get("norm_artist_stripped", "")
                    # A bit loose on artist match here, assuming context is established
                    artist_match = norm_input_artist in lib_artist_norm or fuzz.partial_ratio(norm_input_artist, lib_artist_norm) > 85
                    album_match = lib_entry.get("album") == chosen_album_title_original
                    
                    if artist_match and album_match:
                        tracks_on_selected_album.append(lib_entry)
                
                # Try to sort tracks by track number (if tag exists), then title
                # Assuming duration has tracknumber like '1/12' or just '1'. We need just the number.
                def get_track_num_sort_key(entry):
                    tn_str = entry.get("tracknumber", "9999") # Mutagen key is 'tracknumber'
                    if isinstance(tn_str, str) and '/' in tn_str:
                        tn_str = tn_str.split('/')[0]
                    try:
                        return (int(tn_str), entry.get("title", "").lower())
                    except ValueError:
                        return (9999, entry.get("title", "").lower())

                tracks_on_selected_album.sort(key=get_track_num_sort_key)


                if not tracks_on_selected_album:
                    print(colorize(f"No tracks found in library for album '{chosen_album_title_original}' by '{input_artist}'. This is unexpected.", Colors.RED))
                    logging.error(f"INTERACTIVE (Album Select): No tracks found for album '{chosen_album_title_original}' after selection. Inconsistency?")
                    continue # Go back to album selection

                # 4. Prompt user to choose a track from this album
                while True: # Track selection loop
                    print(f"\n{Colors.UNDERLINE}Tracks on '{chosen_album_title_original}' by '{input_artist}':{Colors.RESET}")
                    track_choices_map = {}
                    track_idx = 1
                    for track_entry in tracks_on_selected_album:
                        live_status = colorize("LIVE", Colors.MAGENTA) if track_entry['entry_is_live'] else colorize("Studio", Colors.GREEN)
                        duration_str = f" [{track_entry['duration']}s]" if track_entry.get('duration', -1) != -1 else ""
                        print(f"  {colorize(f'[{track_idx}]', Colors.BLUE)} {track_entry['title']}{duration_str} - {live_status}")
                        track_choices_map[str(track_idx)] = track_entry
                        track_idx += 1
                    
                    print(f"  {colorize('[B]', Colors.YELLOW)}ack to album selection")
                    track_choices_map['b'] = 'back'
                    print(f"  {colorize('[S]', Colors.RED)}kip original input track")
                    track_choices_map['s'] = 'skip'

                    try:
                        track_prompt_text = colorize("Choose a track (number, B, S): ", Colors.BLUE + Colors.BOLD)
                        track_choice_str = input(track_prompt_text).lower().strip()

                        if track_choice_str in track_choices_map:
                            selected_track_action = track_choices_map[track_choice_str]

                            if selected_track_action == 'skip':
                                print(f"\n{colorize('Skipping original track.', Colors.RED)}")
                                logging.info(f"INTERACTIVE (Album Track Select): User chose [S]kip for '{input_artist} - {input_track}'.")
                                return None # Propagates to skip
                            elif selected_track_action == 'back':
                                logging.info(f"INTERACTIVE (Album Track Select): User chose [B]ack.")
                                break # Breaks from track selection loop, goes back to album selection loop

                            # User chose a track by number
                            chosen_final_track = selected_track_action
                            print(f"\n{colorize('Selected Replacement Track:', Colors.GREEN + Colors.BOLD)}")
                            print(f"  Artist: {chosen_final_track['artist']} - Title: {chosen_final_track['title']} (Album: {chosen_final_track.get('album', 'N/A')})")
                            logging.info(f"INTERACTIVE (Album Track Select): User CHOSE track '{chosen_final_track['path']}' as replacement for '{input_artist} - {input_track}'.")
                            return chosen_final_track # This is the selected library entry dict
                        else:
                            print(colorize(f"Invalid choice '{track_choice_str}'. Please enter a valid number, B, or S.", Colors.RED))
                    except (EOFError, KeyboardInterrupt):
                        print(colorize("\nInput interrupted. Assuming Skip.", Colors.RED))
                        logging.warning(f"INTERACTIVE (Album Track Select): EOF/KeyboardInterrupt. Assuming skip for '{input_artist} - {input_track}'.")
                        return None
                # End of track selection loop (if 'B' was chosen, it re-loops to album selection)
                if track_choice_str == 'b': # Check if we broke from inner loop due to 'back'
                    continue # Go to next iteration of album selection loop
            
            else: # Invalid album choice
                print(colorize(f"Invalid choice '{album_choice_str}'. Please enter a valid number, S, or R.", Colors.RED))

        except (EOFError, KeyboardInterrupt):
            print(colorize("\nInput interrupted. Assuming Skip.", Colors.RED))
            logging.warning(f"INTERACTIVE (Album Select): EOF/KeyboardInterrupt. Assuming skip for '{input_artist} - {input_track}'.")
            return None
    # End of album selection loop

# --- Interactive Prompt ---
def prompt_user_for_choice(input_artist, input_track, candidates, artist_matches, input_live_format, threshold):
    """ Presents choices to the user using colors for clarity. """
    # --- Header ---
    print("-" * 70)
    print(f"{Colors.BOLD}{Colors.CYAN}INTERACTIVE PROMPT for:{Colors.RESET}")
    print(f"  Input: {colorize(input_artist, Colors.BOLD)} - {colorize(input_track, Colors.BOLD)}")
    print(f"  (Input Specified Live: {colorize(str(input_live_format), Colors.BOLD)})")
    print("-" * 70)

    valid_choices = {}
    numeric_choice_counter = 1

    # --- Present numbered candidate choices ---
    if candidates:
        print(f"{Colors.UNDERLINE}Potential Matches Found (ranked by score):{Colors.RESET}")
        max_display = 7
        displayed_count = 0
        for entry in candidates:
             # Only display candidates meeting threshold for user clarity
             if entry.get('_current_score_before_prompt', -1) >= threshold:
                score = entry['_current_score_before_prompt']
                live_status = colorize("LIVE", Colors.MAGENTA) if entry['entry_is_live'] else colorize("Studio", Colors.GREEN)
                album_str = f" (Album: {entry.get('album', 'Unknown')})" if entry.get('album') else ""
                duration_str = f" [{entry['duration']}s]" if entry.get('duration', -1) != -1 else ""
                filename = Path(entry['path']).name # Show only filename

                live_mismatch_note = ""
                if input_live_format != entry['entry_is_live']:
                    penalty_note = "(Penalty Applied)" if entry.get('_penalty_applied', False) else ""
                    live_mismatch_note = colorize(f" <-- NOTE: Live/Studio mismatch! {penalty_note}", Colors.YELLOW)

                print(f"  {colorize(f'[{numeric_choice_counter}]', Colors.BLUE)} {entry['artist']} - {entry['title']}{album_str}{duration_str}")
                print(f"      Score: {colorize(f'{score:.1f}', Colors.BOLD)} | Type: {live_status} | File: {filename}{live_mismatch_note}")

                valid_choices[str(numeric_choice_counter)] = entry
                numeric_choice_counter += 1
                displayed_count += 1
                if displayed_count >= max_display and len(candidates) > displayed_count:
                     # Check if remaining candidates are also above threshold before printing ellipsis
                     remaining_above_thresh = sum(1 for e in candidates[displayed_count:] if e.get('_current_score_before_prompt', -1) >= threshold)
                     if remaining_above_thresh > 0:
                          print(colorize(f"      ... (and {remaining_above_thresh} more candidates above threshold)", Colors.YELLOW))
                     break # Stop displaying choices
        if displayed_count == 0:
             print(colorize("No matches found meeting the display threshold.", Colors.YELLOW))

    else:
        print(colorize("No direct title matches found meeting threshold.", Colors.YELLOW))

    # --- Present Action choices ---
    print(f"\n{Colors.UNDERLINE}Choose an action:{Colors.RESET}")
    print(f"  {colorize('[S]', Colors.RED)}kip this track")
    valid_choices['s'] = None

    if artist_matches: # Only show Random if artist matches were found
        print(f"  {colorize('[R]', Colors.YELLOW)}andom track from library by artist containing '{input_artist}'")
        valid_choices['r'] = 'random' # Special marker

    # --- Context Notes ---
    found_live = any(c.get('entry_is_live', False) for c in candidates)
    found_studio = any(not c.get('entry_is_live', True) for c in candidates)
    # Only show notes if candidates meeting threshold were actually displayed
    if candidates and displayed_count > 0:
        if not input_live_format and found_live and not found_studio:
            print(colorize("  NOTE: Input track seems Studio, only LIVE version(s) met threshold.", Colors.YELLOW))
        elif input_live_format and not found_live and found_studio:
            print(colorize("  NOTE: Input track seems LIVE, only STUDIO version(s) met threshold.", Colors.YELLOW))
        elif found_live and found_studio:
             print(colorize("  NOTE: Both Studio and LIVE versions found. Check types listed above.", Colors.YELLOW))

    # --- Get User Input ---
    while True:
        try:
            prompt_text = colorize("Your choice (number, S, R): ", Colors.BLUE + Colors.BOLD)
            choice = input(prompt_text).lower().strip()

            if choice in valid_choices:
                selected_option = valid_choices[choice]

                if selected_option == 'random':
                    if artist_matches:
                        random_entry = random.choice(artist_matches)
                        print(f"\n{colorize('Selected Random Track:', Colors.YELLOW + Colors.BOLD)}")
                        print(f"  Artist: {random_entry['artist']}")
                        print(f"  Title:  {random_entry['title']}")
                        print(f"  Path:   {random_entry['path']}")
                        logging.info(f"INTERACTIVE: User chose [R]andom track for '{input_artist} - {input_track}'. Selected: {random_entry['path']}")
                        return random_entry
                    else:
                        print(colorize("Error: No tracks found for this artist to pick randomly from.", Colors.RED))
                        logging.warning(f"INTERACTIVE: User chose [R]andom for '{input_artist} - {input_track}', but no artist matches available unexpectedly.")
                        continue # Re-prompt

                elif selected_option is None:
                    print(f"\n{colorize('Skipping track.', Colors.RED)}")
                    logging.info(f"INTERACTIVE: User chose [S]kip for '{input_artist} - {input_track}'.")
                    return None

                else:
                    print(f"\n{colorize(f'Selected Match [{choice}]:', Colors.GREEN + Colors.BOLD)}")
                    print(f"  Artist: {selected_option['artist']}")
                    print(f"  Title:  {selected_option['title']}")
                    print(f"  Path:   {selected_option['path']}")
                    logging.info(f"INTERACTIVE: User chose candidate [{choice}] for '{input_artist} - {input_track}'. Selected: {selected_option['path']}")
                    return selected_option
            else:
                print(colorize(f"Invalid choice '{choice}'. Please enter a valid number from the list above, or S/R.", Colors.RED))
        except EOFError:
             print(colorize("\nEOF received. Assuming Skip.", Colors.RED))
             logging.warning(f"INTERACTIVE: EOF received during prompt for '{input_artist} - {input_track}'. Assuming skip.")
             return None
        except KeyboardInterrupt:
            print(colorize("\nKeyboard Interrupt. Assuming Skip.", Colors.RED))
            logging.warning(f"INTERACTIVE: KeyboardInterrupt during prompt for '{input_artist} - {input_track}'. Assuming skip.")
            # Optional: raise KeyboardInterrupt again here if you want the whole script to stop
            return None

# --- Track Matching Logic ---
# (Inside playlist_maker.py)
# Ensure these are accessible:
# from fuzzywuzzy import fuzz
# import logging
# from .your_module import ( # Or however you import these
#     library_index, INTERACTIVE_MODE, Colors, colorize,
#     normalize_and_detect_specific_live_format,
#     prompt_user_for_choice, prompt_album_selection_or_skip # New album prompt
# )
# import random # Ensure random is imported

def find_track_in_index(input_artist, input_track, match_threshold, live_penalty_factor):
    """
    Finds the best match in the library_index for the input track,
    or offers album selection if no direct match and in interactive mode.
    """
    global library_index # Assuming library_index is a global list of track dictionaries
    global INTERACTIVE_MODE # Assuming INTERACTIVE_MODE is a global boolean

    norm_input_artist_match_str, input_artist_has_live_format = normalize_and_detect_specific_live_format(input_artist)
    norm_input_title_match_str, input_title_has_live_format = normalize_and_detect_specific_live_format(input_track)
    is_input_explicitly_live_format = input_artist_has_live_format or input_title_has_live_format

    logging.debug(f"BEGIN SEARCH (Interactive: {INTERACTIVE_MODE}): For Input='{input_artist} - {input_track}' (InputLiveFmt: {is_input_explicitly_live_format})")
    logging.debug(f"  Norm Input Match: Artist='{norm_input_artist_match_str}', Title='{norm_input_title_match_str}'")

    # --- Find initial artist candidates ---
    candidate_artist_entries = [] # Tracks by artists whose name somewhat matches the input artist
    processed_artists_for_debug = set()
    best_artist_substring_miss_entry, best_artist_substring_miss_score = None, -1

    for entry in library_index:
        norm_library_artist_stripped = entry["norm_artist_stripped"]
        # Substring match for artist (input artist found within library artist)
        if norm_input_artist_match_str and norm_library_artist_stripped and norm_input_artist_match_str in norm_library_artist_stripped:
            candidate_artist_entries.append(entry)
            if norm_library_artist_stripped not in processed_artists_for_debug:
                logging.debug(f"  Artist Substring Candidate: Input '{norm_input_artist_match_str}' in Lib Artist '{norm_library_artist_stripped}' (Path: {entry['path']})")
                processed_artists_for_debug.add(norm_library_artist_stripped)
        # Empty input artist matches empty library artist (e.g., "Various Artists" or unknown)
        elif not norm_input_artist_match_str and not norm_library_artist_stripped:
             candidate_artist_entries.append(entry)
             if "UNKNOWN_ARTIST_EMPTY_INPUT" not in processed_artists_for_debug:
                 logging.debug(f"  Artist Empty Match: Path: {entry['path']}")
                 processed_artists_for_debug.add("UNKNOWN_ARTIST_EMPTY_INPUT")
        # Track fuzzy misses for artist for logging purposes
        else:
             if norm_input_artist_match_str and norm_library_artist_stripped:
                current_artist_fuzzy_score = fuzz.ratio(norm_input_artist_match_str, norm_library_artist_stripped)
                if current_artist_fuzzy_score > best_artist_substring_miss_score:
                    best_artist_substring_miss_score = current_artist_fuzzy_score
                    best_artist_substring_miss_entry = entry

    if not candidate_artist_entries:
        miss_info = f"NO ARTIST MATCH: Input artist '{input_artist}' (Norm: '{norm_input_artist_match_str}') not found as substring in any library artist."
        if best_artist_substring_miss_entry:
             miss_info += (f"\n     -> Closest Fuzzy Artist Miss: '{best_artist_substring_miss_entry['artist']}' "
                           f"(Norm: '{best_artist_substring_miss_entry['norm_artist_stripped']}', "
                           f"Score: {best_artist_substring_miss_score}, Path: {best_artist_substring_miss_entry['path']})")
        logging.warning(miss_info)
        if INTERACTIVE_MODE:
             print(colorize(f"\nNo potential artists found containing '{input_artist}'.", Colors.YELLOW))
             # prompt_user_for_choice handles 'S'kip when no candidates and no artist_matches are passed
             return prompt_user_for_choice(input_artist, input_track, [], [], is_input_explicitly_live_format, match_threshold)
        else:
             return None

    logging.info(f"Found {len(candidate_artist_entries)} entries potentially matching artist '{input_artist}'. Now matching title '{input_track}'.")

    # --- Score all potential title matches for the found artists ---
    scored_candidates = [] # List to hold qualified candidates' dictionaries
    all_title_misses_for_logging = [] # Store tuples: (final_score, entry_dict) for logging

    for entry in candidate_artist_entries:
        title_meta_score = fuzz.ratio(norm_input_title_match_str, entry["norm_title_stripped"]) if entry["norm_title_stripped"] else -1
        filename_score_for_title = fuzz.token_set_ratio(norm_input_title_match_str, entry["norm_filename_stripped"])
        logging.debug(f"  Testing entry '{Path(entry['path']).name}' (Live: {entry['entry_is_live']}): TitleScore={title_meta_score}, FilenameScore={filename_score_for_title}")

        current_base_score = max(title_meta_score, filename_score_for_title)

        # Consider slightly below threshold to allow bonuses/penalties to bring it up
        if current_base_score >= (match_threshold - 15):
             adjusted_score = current_base_score
             # Apply artist match bonus (more bonus for exact artist match)
             if entry["norm_artist_stripped"] == norm_input_artist_match_str:
                 artist_bonus = 1.0 # Small flat bonus for exact artist on a candidate
             else:
                 # Weighted bonus based on how well the library artist matched input artist (already substring matched)
                 library_artist_match_to_input_artist = fuzz.ratio(norm_input_artist_match_str, entry["norm_artist_stripped"])
                 artist_bonus = (library_artist_match_to_input_artist / 100.0) * 0.5 # Scaled bonus
             adjusted_score += artist_bonus
             adjusted_score = min(adjusted_score, 100.0) # Cap score at 100

             original_score_before_penalty = adjusted_score
             penalty_applied = False
             if not is_input_explicitly_live_format and entry["entry_is_live"]:
                 adjusted_score *= live_penalty_factor
                 penalty_applied = True
                 logging.debug(f"      Applied Live Penalty: {original_score_before_penalty:.1f} * {live_penalty_factor} -> {adjusted_score:.1f}")

             # Store temporary scores on the entry dictionary for sorting and display in prompt
             entry['_current_score_before_prompt'] = adjusted_score
             entry['_original_score'] = original_score_before_penalty
             entry['_penalty_applied'] = penalty_applied

             scored_candidates.append(entry)
        else:
            all_title_misses_for_logging.append((current_base_score, entry)) # Track low base scores too
            logging.debug(f"    Candidate Base Score Too Low (Base: {current_base_score:.1f}, Path: {entry['path']})")

    # --- Filter and Decide Action ---
    # Keep only candidates meeting threshold *after* all scoring/penalties
    qualified_candidates = [c for c in scored_candidates if c.get('_current_score_before_prompt', -1) >= match_threshold]
    qualified_candidates.sort(key=lambda x: x.get('_current_score_before_prompt', -1), reverse=True)

    if not qualified_candidates:
        # No candidates met the final threshold for a direct track match.
        log_msg = f"NO DIRECT MATCH: No tracks found for '{input_artist} - {input_track}' meeting threshold {match_threshold} after scoring."
        # Log the best overall miss (from *all* candidates attempted)
        all_misses_combined_for_logging = all_title_misses_for_logging + \
                                           [(c['_current_score_before_prompt'], c) for c in scored_candidates if c not in qualified_candidates]
        if all_misses_combined_for_logging:
            all_misses_combined_for_logging.sort(key=lambda x: x[0], reverse=True)
            best_miss_score, best_miss_entry = all_misses_combined_for_logging[0]
            log_msg += (f"\n     -> Closest Miss (overall): '{best_miss_entry['artist']} - {best_miss_entry['title']}' "
                        f"(Final Score: {best_miss_score:.1f}, Path: {best_miss_entry['path']})")
        logging.warning(log_msg)

        if INTERACTIVE_MODE and candidate_artist_entries: # We have other tracks by this artist
            print(colorize(f"\nNo direct match found meeting threshold for '{input_artist} - {input_track}'.", Colors.YELLOW))
            # Offer album selection using all tracks by the artist we found earlier
            chosen_entry_via_album = prompt_album_selection_or_skip(
                input_artist,
                input_track,
                candidate_artist_entries, # All library entries matching the input artist name
                is_input_explicitly_live_format, # Pass this for context, though album prompt may not use it directly
                match_threshold # Pass for consistency, though album prompt might ignore it for its own listings
            )
            # chosen_entry_via_album will be a track dict or None
            # If it's a dict, it's already a library entry, no need to pop temporary scores as they weren't added
            return chosen_entry_via_album
        elif INTERACTIVE_MODE: # No artist context or some other issue
             print(colorize(f"\nNo direct match found for '{input_artist} - {input_track}' and no other tracks by this artist in library context.", Colors.YELLOW))
             # Fallback to the standard prompt_user_for_choice which will only offer Skip or Random (if artist_matches is non-empty)
             # Here, scored_candidates will be empty (or sub-threshold), so prompt will show few/no numbered choices.
             return prompt_user_for_choice(input_artist, input_track, scored_candidates, candidate_artist_entries, is_input_explicitly_live_format, match_threshold)
        else: # Not interactive
            return None

    # --- We have at least one QUALIFIED candidate for a direct track match ---
    # (This part means qualified_candidates is not empty)

    best_overall_match = None # Initialize

    # If NOT interactive OR only ONE qualified candidate: Use automatic logic
    if not INTERACTIVE_MODE or len(qualified_candidates) == 1:
         logging.debug("Using Automatic/Single Qualified Candidate Logic for direct track match.")
         
         # Refined automatic selection logic:
         # Prioritize based on input live format, then best score.
         best_candidate_of_correct_live_type = None
         best_candidate_of_other_live_type = None

         for cand in qualified_candidates:
             if cand['entry_is_live'] == is_input_explicitly_live_format:
                 if best_candidate_of_correct_live_type is None or \
                    cand['_current_score_before_prompt'] > best_candidate_of_correct_live_type['_current_score_before_prompt']:
                     best_candidate_of_correct_live_type = cand
             else:
                 if best_candidate_of_other_live_type is None or \
                    cand['_current_score_before_prompt'] > best_candidate_of_other_live_type['_current_score_before_prompt']:
                     best_candidate_of_other_live_type = cand
        
         if best_candidate_of_correct_live_type:
             best_overall_match = best_candidate_of_correct_live_type
             logging.info(f"AUTO/SINGLE: Selected matching live type. InputLive: {is_input_explicitly_live_format}, CandLive: {best_overall_match['entry_is_live']}")
         elif best_candidate_of_other_live_type:
             best_overall_match = best_candidate_of_other_live_type
             logging.warning(f"AUTO/SINGLE: Selected different live type (no matching type found). InputLive: {is_input_explicitly_live_format}, CandLive: {best_overall_match['entry_is_live']}")
         else: # Should not happen if qualified_candidates is not empty
             best_overall_match = qualified_candidates[0] # Fallback to highest score
             logging.error("AUTO/SINGLE: Logic error in type matching, fell back to highest score.")


         if best_overall_match: # Ensure we have a selection
             final_score = best_overall_match.get('_current_score_before_prompt', -1)
             logging.info(f"MATCHED (Auto/Single Direct): '{input_artist} - {input_track}' -> '{best_overall_match['path']}' Score: {final_score:.1f}")
             # Clean up temporary keys added for scoring/prompting
             for key_to_pop in ['_current_score_before_prompt', '_original_score', '_penalty_applied']:
                 best_overall_match.pop(key_to_pop, None)
             return best_overall_match
         else: # Should ideally not be reached if qualified_candidates was non-empty
             logging.error("AUTO/SINGLE: No best_overall_match selected despite qualified_candidates existing.")
             return None


    else: # Interactive mode AND multiple QUALIFIED direct track candidates
        logging.info(f"INTERACTIVE: Multiple ({len(qualified_candidates)}) qualified direct track matches found for '{input_artist} - {input_track}'. Prompting user.")
        chosen_entry = prompt_user_for_choice(
            input_artist=input_artist,
            input_track=input_track,
            candidates=qualified_candidates, # Pass only those meeting threshold
            artist_matches=candidate_artist_entries, # Full list for random choice by artist
            input_live_format=is_input_explicitly_live_format,
            threshold=match_threshold
        )
        if chosen_entry: # Clean up temp keys if user didn't skip and chose a candidate
            for key_to_pop in ['_current_score_before_prompt', '_original_score', '_penalty_applied']:
                chosen_entry.pop(key_to_pop, None)
        return chosen_entry # Can be a track dict (from direct choice or random) or None (if skipped)

# --- Playlist Reading ---
def read_playlist_file(playlist_file_path):
    """Reads 'Artist - Track' lines from the input text file."""
    tracks = []; line_num = 0
    try:
        with open(playlist_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line_num += 1; line = line.strip()
                if not line or line.startswith('#'): continue
                if " - " in line:
                    artist, track = line.split(" - ", 1)
                    tracks.append((artist.strip(), track.strip()))
                else:
                    logging.warning(f"Skipping malformed line {line_num} in '{playlist_file_path}': '{line}' (Expected 'Artist - Track')")
                    print(colorize(f"Warning: Skipping malformed line {line_num}: '{line}'", Colors.YELLOW), file=sys.stderr)
    except FileNotFoundError:
         logging.error(f"Input playlist file not found: '{playlist_file_path}'")
         print(colorize(f"Error: Input playlist file '{playlist_file_path}' not found.", Colors.RED), file=sys.stderr)
         sys.exit(1)
    except Exception as e:
         logging.error(f"Error reading playlist file '{playlist_file_path}': {e}", exc_info=True)
         print(colorize(f"Error reading input file '{playlist_file_path}': {e}", Colors.RED), file=sys.stderr)
         sys.exit(1)
    return tracks

# --- Playlist Generation ---
# --- playlist_maker.py (Partial - showing main and generate_playlist) ---

# [Imports: os, sys, mutagen, Path, fuzz, logging, argparse, time, unicodedata, re, datetime, random, configparser, pd (or DummyPandas)]
# [Global Variables: library_index, INTERACTIVE_MODE, PARENTHETICAL_STRIP_REGEX, Colors class, config object, DEFAULT values]
# [Helper Functions: colorize, parse_list, get_config, normalize_and_detect_specific_live_format, normalize_string_for_matching, check_album_for_live_indicators]
# [Function: format_output_filename(format_string, raw_basename, now, default_extension=".m3u")]
# [Function: setup_logging(log_file_path, log_mode)]
# [Function: get_file_metadata(file_path_obj)]
# [Function: scan_library(scan_library_path_str, supported_extensions, live_album_keywords_regex)]
# [Function: prompt_user_for_choice(...)]
# [Function: find_track_in_index(...)]
# [Function: read_playlist_file(playlist_file_path)]


def generate_playlist(tracks, input_playlist_path, output_m3u_filepath_str, mpd_playlist_dir_str,
                      mpd_music_dir_str, match_threshold,
                      missing_tracks_dir_path, live_penalty_factor):
    """Generates the M3U playlist, handling matching and output."""
    global library_index # Ensure it's accessible
    if not library_index: # Check again before processing
        logging.error("Library index is empty. Cannot generate playlist.")
        print(colorize("Error: Music library index is empty. Cannot generate playlist.", Colors.RED), file=sys.stderr)
        # In a real CLI, this might lead to an exit, but as a library func, returning indicates failure.
        return [] # Return empty list to signify no tracks processed or major issue

    try:
        # mpd_music_dir_str is expected to be resolved in main()
        resolved_mpd_music_dir = Path(mpd_music_dir_str)
        if not resolved_mpd_music_dir.is_dir(): # Should be already checked in main(), but good to confirm
            logging.error(f"MPD music directory does not exist or is not a directory: '{resolved_mpd_music_dir}'.")
            print(colorize(f"Error: MPD music directory '{resolved_mpd_music_dir}' not found or invalid. Check config/args.", Colors.RED), file=sys.stderr)
            return [] # Indicate failure
        logging.info(f"Using resolved MPD music directory: {resolved_mpd_music_dir}")
    except Exception as e: # Catch any other issue resolving this critical path
        logging.error(f"Error with MPD music directory '{mpd_music_dir_str}': {e}")
        print(colorize(f"Error with MPD music directory: {e}", Colors.RED), file=sys.stderr)
        return []


    m3u_lines = ["#EXTM3U"]
    skipped_track_inputs = []
    found_count = 0
    total_tracks = len(tracks)

    print(f"\nProcessing {total_tracks} track entries...")
    for index, (artist, track) in enumerate(tracks):
        print(f"\n{colorize(f'[{index + 1}/{total_tracks}]', Colors.CYAN)} Searching for: {artist} - {track}")

        matched_entry = find_track_in_index(artist, track, match_threshold, live_penalty_factor)

        if matched_entry:
            abs_file_path_from_index = Path(matched_entry['path'])
            duration_val = matched_entry.get('duration', -1)
            extinf_artist = matched_entry.get('artist', artist) or artist
            extinf_title = matched_entry.get('title', track) or track

            try:
                relative_path = abs_file_path_from_index.relative_to(resolved_mpd_music_dir)
                m3u_path_string = relative_path.as_posix()

                logging.debug(f"M3U PREP: Input='{artist} - {track}' -> Found='{extinf_artist} - {extinf_title}', Path='{m3u_path_string}', Duration={duration_val}")

                m3u_lines.append(f"#EXTINF:{duration_val},{extinf_artist} - {extinf_title}")
                m3u_lines.append(m3u_path_string)
                found_count += 1
                print(f"  -> {colorize('Found:', Colors.GREEN)} {m3u_path_string}")

            except ValueError as ve: # Path not relative
                reason = f"Path not relative to MPD library tree ({resolved_mpd_music_dir})"
                logging.warning(f"Skipping track (Path Error): '{abs_file_path_from_index}' not within '{resolved_mpd_music_dir}'.")
                skipped_track_inputs.append(f"{artist} - {track} (Reason: {reason} - Path: {abs_file_path_from_index})")
                print(f"  -> {colorize('Skipped:', Colors.YELLOW)} Path not relative to MPD music directory.")
                continue
        else:
            reason = "No suitable match found"
            if INTERACTIVE_MODE:
                 reason = "Skipped by user or no match found/chosen"
            skipped_track_inputs.append(f"{artist} - {track} (Reason: {reason} - see log for details)")
            print(f"  -> {colorize('Skipped:', Colors.RED)} {reason}.")

    # --- Filename Generation & Writing M3U ---
    output_m3u_path = Path(output_m3u_filepath_str) # Convert string path to Path object
    output_dir_for_m3u = output_m3u_path.parent   # Derive output directory from the full M3U path

    try:
        output_dir_for_m3u.mkdir(parents=True, exist_ok=True) # Ensure output dir for M3U exists
        with open(output_m3u_path, "w", encoding="utf-8") as f:
            f.write("\n".join(m3u_lines) + "\n") # Ensure trailing newline
        print(f"\n{colorize('Generated playlist', Colors.GREEN + Colors.BOLD)} ({found_count}/{total_tracks} tracks included): {output_m3u_path}")
        logging.info(f"Generated playlist '{output_m3u_path}' with {found_count} of {total_tracks} input tracks.")
    except Exception as e:
        logging.error(f"Failed to write playlist to {output_m3u_path}: {e}", exc_info=True)
        print(colorize(f"Error writing output playlist {output_m3u_path}: {e}", Colors.RED), file=sys.stderr)
        return skipped_track_inputs # Return what we have, as M3U write failed

    # --- Optionally copy to MPD playlist directory ---
    if mpd_playlist_dir_str:
        try:
            mpd_playlist_path_obj = Path(mpd_playlist_dir_str) # Already resolved in main
            # Target filename for MPD copy is the same as the generated M3U's name
            mpd_target_filename = output_m3u_path.name
            mpd_final_m3u_path = mpd_playlist_path_obj / mpd_target_filename

            if not mpd_playlist_path_obj.is_dir():
                if not mpd_playlist_path_obj.exists():
                    logging.info(f"MPD playlist directory '{mpd_playlist_path_obj}' does not exist. Creating.")
                    mpd_playlist_path_obj.mkdir(parents=True, exist_ok=True)
                else: # Exists but not a directory
                    logging.error(f"MPD playlist path '{mpd_playlist_path_obj}' exists but is not a directory.")
                    # This would typically be an error condition the user needs to fix.
                    # We'll log it and skip copying.
                    raise FileNotFoundError(f"Not a directory: {mpd_playlist_path_obj}")

            with open(mpd_final_m3u_path, "w", encoding="utf-8") as f:
                f.write("\n".join(m3u_lines) + "\n")
            print(f"{colorize('Copied playlist to MPD directory:', Colors.CYAN)} {mpd_final_m3u_path}")
            logging.info(f"Copied playlist to MPD directory: {mpd_final_m3u_path}")
        except (FileNotFoundError, PermissionError, OSError, Exception) as e: # Catch broadly
            logging.error(f"Failed to copy playlist to MPD directory '{mpd_playlist_dir_str}': {e}", exc_info=True)
            print(colorize(f"Warning: Failed to copy playlist to MPD directory '{mpd_playlist_dir_str}': {e}", Colors.YELLOW), file=sys.stderr)

    # --- Write Missing Tracks File ---
    if skipped_track_inputs:
        try:
            # missing_tracks_dir_path is expected to be a resolved Path object from main()
            missing_tracks_dir_path.mkdir(parents=True, exist_ok=True) # Ensure missing tracks dir exists

            # Derive missing tracks filename from the M3U filename stem
            missing_filename_stem = output_m3u_path.stem # e.g., "My_Playlist_2023-01-01"
            missing_filename = f"{missing_filename_stem}-missing-tracks.txt"
            missing_file_full_path = missing_tracks_dir_path / missing_filename

            with open(missing_file_full_path, "w", encoding="utf-8") as f_missing:
                f_missing.write(f"# Input playlist: {input_playlist_path}\n") # Original input playlist path
                f_missing.write(f"# Generated M3U: {output_m3u_path}\n")    # Path to the M3U we created
                f_missing.write(f"# Date Generated: {datetime.now().isoformat()}\n")
                f_missing.write(f"# {len(skipped_track_inputs)} tracks from input file not found or skipped:\n")
                f_missing.write("-" * 30 + "\n")
                for missing_track_info in skipped_track_inputs:
                    f_missing.write(f"{missing_track_info}\n")
            print(f"{colorize('List of missing/skipped tracks saved to:', Colors.YELLOW)} {missing_file_full_path}")
            logging.info(f"List of {len(skipped_track_inputs)} missing/skipped tracks saved to: {missing_file_full_path}")
        except Exception as e:
            logging.error(f"Failed to write missing tracks file to {missing_tracks_dir_path}: {e}", exc_info=True)
            print(colorize(f"Warning: Failed to write missing tracks file: {e}", Colors.YELLOW), file=sys.stderr)

    # --- Log Summary ---
    if skipped_track_inputs:
        mf_name_for_log = missing_filename if 'missing_filename' in locals() else 'the missing-tracks file'
        logging.warning(f"--- Summary: Skipped {len(skipped_track_inputs)} tracks. See details in '{mf_name_for_log}' and debug logs. ---")
        print(colorize(f"\nWarning: Skipped {len(skipped_track_inputs)} out of {total_tracks} input tracks. See log/missing file.", Colors.YELLOW))
    else:
        logging.info("--- Summary: All tracks from input file were matched and included successfully. ---")
        print(colorize("\nAll tracks included successfully.", Colors.GREEN))

    return skipped_track_inputs

# --- Main Execution ---
def main(argv_list=None): # Can accept arguments for GUI usage
    global INTERACTIVE_MODE
    global PARENTHETICAL_STRIP_REGEX
    global config # Ensure global config is accessible

    # --- Determine Script Directory ---
    script_dir = Path.cwd() # Default if __file__ fails
    try:
        script_dir = Path(__file__).parent.resolve()
    except NameError:
        pass # Keep CWD if __file__ not defined (e.g. interactive interpreter)

    # --- Determine Config File Paths ---
    config_path_local = script_dir / CONFIG_FILENAME_LOCAL
    config_path_user = CONFIG_DIR_USER / CONFIG_FILENAME_USER

    # --- Load Configuration Files ---
    try:
        CONFIG_DIR_USER.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"{Colors.YELLOW}Warning:{Colors.RESET} Could not create user config directory {CONFIG_DIR_USER}: {e}", file=sys.stderr)
    loaded_files = config.read([config_path_local, config_path_user]) # Later files override earlier

    # --- Argument Parser Setup ---
    parser = argparse.ArgumentParser(
        description=f"{Colors.BOLD}Generate M3U playlists by matching 'Artist - Track' lines against a music library.{Colors.RESET}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Shows defaults in help
    )

    parser.add_argument("playlist_file", help="Input text file (one 'Artist - Track' per line).")
    parser.add_argument("-l", "--library", default=None, help=f"Music library path. Cfg: Paths.library, Def: {DEFAULT_SCAN_LIBRARY}")
    parser.add_argument("--mpd-music-dir", default=None, help=f"MPD music_directory path. Cfg: Paths.mpd_music_dir, Def: {DEFAULT_MPD_MUSIC_DIR_CONF}")
    parser.add_argument("-o", "--output-dir", default=None, help=f"Output dir for M3U. Cfg: Paths.output_dir, Def: {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--missing-dir", default=None, help=f"Dir for missing tracks list. Cfg: Paths.missing_dir, Def: {DEFAULT_MISSING_TRACKS_DIR}")
    parser.add_argument("-m", "--mpd-playlist-dir", default=None, nargs='?', const="USE_DEFAULT_OR_CONFIG",
                        help="Copy M3U to MPD dir. No value=use default/config. Cfg: Paths.mpd_playlist_dir")
    parser.add_argument("-t", "--threshold", type=int, default=None, choices=range(0, 101), metavar="[0-100]",
                        help=f"Min match score [0-100]. Cfg: Matching.threshold, Def: {DEFAULT_MATCH_THRESHOLD}")
    parser.add_argument("--live-penalty", type=float, default=None, metavar="[0.0-1.0]",
                        help=f"Penalty for unwanted live match. Cfg: Matching.live_penalty, Def: {DEFAULT_LIVE_PENALTY_FACTOR}")
    parser.add_argument(
        "--output-name-format", # New argument
        default=None,
        type=str,
        help="Custom format string for the output M3U filename. "
             "Placeholders: {basename}, {basename:transforms}, {YYYY}, {YY}, {MM}, {DD}, {hh}, {mm}, {ss}. "
             "Transforms for basename (e.g., {basename:cp}): "
             "'c'-capitalize words, 'u'-uppercase, 'l'-lowercase; "
             "'p'-prettify spaces, 's'-hyphenate, '_'-underscorify. "
             "Example: \"{basename:c}_{YYYY}-{MM}-{DD}.m3u\""
    )
    parser.add_argument("--log-file", type=Path, default=None, help=f"Log file path. Cfg: Logging.log_file, Def: <script_dir>/{DEFAULT_LOG_FILE_NAME}")
    parser.add_argument("--log-mode", choices=['append', 'overwrite'], default=None, help="Log file mode. Cfg: Logging.log_mode, Def: overwrite")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=None, help="Log level for file. Cfg: Logging.log_level, Def: INFO")
    parser.add_argument("-e", "--extensions", nargs='+', default=None, help=f"Audio extensions. Cfg: General.extensions, Def: {' '.join(DEFAULT_SUPPORTED_EXTENSIONS)}")
    parser.add_argument("--live-album-keywords", nargs='+', default=None, help="Regex patterns for live albums. Cfg: Matching.live_album_keywords")
    parser.add_argument("--strip-keywords", nargs='+', default=None, help="Keywords to strip from (). Cfg: Matching.strip_keywords")
    parser.add_argument("-i", "--interactive", action="store_true", default=None, help="Enable interactive mode. Cfg: General.interactive, Def: false")
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {SCRIPT_VERSION}', # %(prog)s will be replaced by the script name
        help="Show program's version number and exit."
    )

    if argv_list is None: # Running from command line
        args = parser.parse_args()
    else: # Called with specific args (e.g., from GUI)
        args = parser.parse_args(argv_list)

    # --- Determine Final Configuration Values (using args or config or defaults) ---
    final_library_path = args.library if args.library is not None else get_config("Paths", "library", DEFAULT_SCAN_LIBRARY)
    final_mpd_music_dir = args.mpd_music_dir if args.mpd_music_dir is not None else get_config("Paths", "mpd_music_dir", DEFAULT_MPD_MUSIC_DIR_CONF)
    final_output_dir_str = args.output_dir if args.output_dir is not None else get_config("Paths", "output_dir", DEFAULT_OUTPUT_DIR)
    final_missing_dir_str = args.missing_dir if args.missing_dir is not None else get_config("Paths", "missing_dir", DEFAULT_MISSING_TRACKS_DIR)

    # MPD Playlist Dir Logic
    final_mpd_playlist_dir_str = None
    if args.mpd_playlist_dir is not None:
        if args.mpd_playlist_dir == "USE_DEFAULT_OR_CONFIG":
             config_val = get_config("Paths", "mpd_playlist_dir", fallback="USE_DEFAULT_CONST")
             if config_val == "USE_DEFAULT_CONST": final_mpd_playlist_dir_str = DEFAULT_MPD_PLAYLIST_DIR_CONF
             elif config_val: final_mpd_playlist_dir_str = config_val
             else: final_mpd_playlist_dir_str = None # Explicitly disabled ("" in config)
        else: final_mpd_playlist_dir_str = args.mpd_playlist_dir
    else:
        config_val = get_config("Paths", "mpd_playlist_dir", fallback=None)
        final_mpd_playlist_dir_str = config_val if config_val else None

    final_threshold = args.threshold if args.threshold is not None else get_config("Matching", "threshold", DEFAULT_MATCH_THRESHOLD, int)
    final_live_penalty = args.live_penalty if args.live_penalty is not None else get_config("Matching", "live_penalty", DEFAULT_LIVE_PENALTY_FACTOR, float)
    final_live_album_kws = args.live_album_keywords if args.live_album_keywords is not None else get_config("Matching", "live_album_keywords", DEFAULT_LIVE_ALBUM_KEYWORDS, list)
    final_strip_keywords = args.strip_keywords if args.strip_keywords is not None else get_config("Matching", "strip_keywords", DEFAULT_PARENTHETICAL_STRIP_KEYWORDS, list)

    # Log File Path
    default_log_path = script_dir / DEFAULT_LOG_FILE_NAME
    config_log_file_str = get_config("Logging", "log_file", str(default_log_path))
    final_log_file_path_obj = args.log_file if args.log_file is not None else Path(config_log_file_str)

    final_log_mode = args.log_mode if args.log_mode is not None else get_config("Logging", "log_mode", "overwrite")
    final_log_level_str = args.log_level if args.log_level is not None else get_config("Logging", "log_level", "INFO")

    final_extensions = args.extensions if args.extensions is not None else get_config("General", "extensions", DEFAULT_SUPPORTED_EXTENSIONS, list)

    if args.interactive is True:
         final_interactive = True
    elif args.interactive is None:
         final_interactive = get_config("General", "interactive", fallback=False, expected_type=bool)
    else:
        final_interactive = False
    INTERACTIVE_MODE = final_interactive

    # --- Expand User Paths (Tilde Expansion) ---
    final_library_path = os.path.expanduser(final_library_path)
    final_mpd_music_dir_str = os.path.expanduser(final_mpd_music_dir) # Renamed to avoid clash with Path obj
    final_output_dir_str = os.path.expanduser(final_output_dir_str)
    final_missing_dir_str = os.path.expanduser(final_missing_dir_str)
    if final_mpd_playlist_dir_str: final_mpd_playlist_dir_str = os.path.expanduser(final_mpd_playlist_dir_str)

    try: # Resolve log path *after* expansion
        final_log_file_path_obj = Path(os.path.expanduser(str(final_log_file_path_obj))).resolve()
    except Exception as e:
         print(f"{Colors.YELLOW}Warning:{Colors.RESET} Could not fully resolve log path '{final_log_file_path_obj}': {e}. Using unverified path.", file=sys.stderr)
         final_log_file_path_obj = Path(os.path.expanduser(str(final_log_file_path_obj))) # Use expanded path if resolve fails

    # --- Post-processing / Validation ---
    if not (0 <= final_threshold <= 100): parser.error(f"--threshold ({final_threshold}) must be between 0 and 100.")
    if not (0.0 <= final_live_penalty <= 1.0): parser.error(f"--live-penalty ({final_live_penalty}) must be between 0.0 and 1.0.")
    final_supported_extensions_tuple = tuple(ext.lower() if ext.startswith('.') else '.' + ext.lower() for ext in final_extensions if ext)

    # --- Setup Logging ---
    setup_logging(final_log_file_path_obj, final_log_mode)
    log_level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    final_log_level = log_level_map.get(final_log_level_str.upper(), logging.INFO)
    logging.getLogger().setLevel(final_log_level)

    # --- Log Effective Settings ---
    logging.info("="*30 + " Playlist Maker Started " + "="*30)
    logging.info(f"Version: {SCRIPT_VERSION}") # Use the SCRIPT_VERSION constant
    # ... (logging all final settings as before)
    logging.info(f"  Output Filename Format (CLI arg): {args.output_name_format if args.output_name_format else 'Using default naming'}")


    # --- Compile Regex ---
    try:
        live_album_keywords_regex_obj = None
        if final_live_album_kws:
             live_album_regex_pattern = r"(" + "|".join(final_live_album_kws) + r")"
             live_album_keywords_regex_obj = re.compile(live_album_regex_pattern, re.IGNORECASE)
             logging.info(f"Using live album regex: {live_album_regex_pattern}")

        PARENTHETICAL_STRIP_REGEX = None
        if final_strip_keywords:
            strip_keywords_pattern = r"|".join(r"(?:\W|^)" + re.escape(kw) + r"(?:\W|$)" for kw in final_strip_keywords)
            PARENTHETICAL_STRIP_REGEX = re.compile(strip_keywords_pattern, re.IGNORECASE)
            logging.info(f"Using parenthetical strip regex: {strip_keywords_pattern}")
    except re.error as e:
        logging.error(f"Invalid regex pattern derived from config/defaults: {e}")
        print(colorize(f"Error: Invalid regex pattern in keywords: {e}", Colors.RED), file=sys.stderr)
        return {"success": False, "error": f"Invalid regex pattern: {e}", "skipped_tracks": []} # For GUI


    # --- Resolve Essential Paths to Path Objects ---
    try:
        input_playlist_file_abs_path = Path(args.playlist_file).resolve(strict=True)
        library_abs_path = Path(final_library_path).resolve(strict=True)
        mpd_music_dir_abs_path = Path(final_mpd_music_dir_str).resolve(strict=True)
        output_dir_abs_path = Path(final_output_dir_str).resolve() # .resolve() is fine, mkdir later handles existence
        missing_tracks_dir_abs_path = Path(final_missing_dir_str).resolve()

        logging.info(f"Resolved Input Playlist: {input_playlist_file_abs_path}")
        # (Library, MPD, Output dirs already logged or implied)
    except FileNotFoundError as e:
        logging.error(f"Essential path does not exist after resolving: {e}. Exiting.")
        print(colorize(f"Error: Essential path not found: {e}", Colors.RED), file=sys.stderr)
        return {"success": False, "error": f"Essential path not found: {e}", "skipped_tracks": []} # For GUI
    except Exception as e:
        logging.error(f"Error resolving final paths: {e}", exc_info=True)
        print(colorize(f"Error resolving paths: {e}", Colors.RED), file=sys.stderr)
        return {"success": False, "error": f"Error resolving paths: {e}", "skipped_tracks": []} # For GUI


    # --- Filename Generation for Output M3U ---
    raw_playlist_basename = input_playlist_file_abs_path.stem
    current_time = datetime.now()
    generated_m3u_filename = format_output_filename(
        args.output_name_format, # This is the format string from CLI (can be None)
        raw_playlist_basename,
        current_time
    )
    logging.info(f"Derived M3U output filename: {generated_m3u_filename}")
    full_output_m3u_filepath = output_dir_abs_path / generated_m3u_filename


    # --- Main Execution Flow ---
    print(f"Reading input file: {input_playlist_file_abs_path}...")
    tracks = read_playlist_file(str(input_playlist_file_abs_path)) # Function expects string path
    if not tracks:
        logging.error("Exiting: No valid track entries read.")
        print(colorize(f"Error: No valid 'Artist - Track' lines found in '{input_playlist_file_abs_path}'.", Colors.RED), file=sys.stderr)
        return {"success": False, "error": "No valid tracks in input file", "skipped_tracks": []}
    print(f"Read {len(tracks)} track entries.")

    scan_library(str(library_abs_path), final_supported_extensions_tuple, live_album_keywords_regex_obj)
    if not library_index: # scan_library logs errors internally
        return {"success": False, "error": "Library scan found no tracks", "skipped_tracks": []}
    print(colorize(f"Scan complete. Found {len(library_index)} tracks in library index.", Colors.GREEN))

    # --- Call generate_playlist ---
    skipped_tracks_list = generate_playlist(
        tracks=tracks,
        input_playlist_path=str(input_playlist_file_abs_path),
        output_m3u_filepath_str=str(full_output_m3u_filepath), # Pass the full generated path
        mpd_playlist_dir_str=final_mpd_playlist_dir_str, # Can be None
        mpd_music_dir_str=str(mpd_music_dir_abs_path),
        match_threshold=final_threshold,
        missing_tracks_dir_path=missing_tracks_dir_abs_path, # Pass Path object
        live_penalty_factor=final_live_penalty
    )

    logging.info("Playlist Maker script processing completed.")
    print(f"\n{colorize('DONE', Colors.BOLD + Colors.GREEN)}")

    return {"success": True, "skipped_tracks": skipped_tracks_list}

# --- Entry Point ---
if __name__ == "__main__":
    # Dummy pandas for duration checking if real pandas not installed
    # This setup_logging call is for when the script is run directly.
    # If main() is imported, it's expected the importer (GUI) might set up its own logging
    # or main() itself will re-init logging based on its args.
    # The initial logging setup here is basic, mainly to catch very early errors
    # before main() fully configures it based on arguments.
    temp_log_path = Path.cwd() / DEFAULT_LOG_FILE_NAME # Default to CWD if run directly before path resolution
    try:
        if Path(__file__).parent.is_dir():
            temp_log_path = Path(__file__).parent / DEFAULT_LOG_FILE_NAME
    except NameError: # __file__ not defined (e.g. in interpreter)
        pass
    
    # Basic initial logging setup - will be reconfigured in main() based on args/config
    # This ensures any errors *before* main's full logging setup are caught.
    # Minimal console output at this stage.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # Execute main function
    try:
        main() # This will call the full main function defined above
    except SystemExit as e:
        # Argparse calls sys.exit on errors like -h or invalid arguments.
        # This allows the script to exit cleanly with the correct code.
        # No need to log here as argparse usually prints its own messages.
        sys.exit(e.code)
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received, shutting down GUI.")
        print("\nPlaylist Maker GUI closed via Ctrl+C.") # Print to console
        sys.exit(1) # Exit with a non-zero code for interruption
    except Exception as e:
        # Catch any other unhandled exceptions from main() or other top-level code
        # Log with full traceback for debugging
        logging.critical(f"Unhandled critical error at top level: {e}", exc_info=True)
        # Print a user-friendly error message as well
        print(colorize(f"\nCritical error: {e}\nPlease check the log file for more details.", Colors.RED), file=sys.stderr)
        sys.exit(1) # Exit with a non-zero code