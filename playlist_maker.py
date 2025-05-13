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
def find_track_in_index(input_artist, input_track, match_threshold, live_penalty_factor):
    """Finds the best match in the library_index for the input track."""
    global library_index
    global INTERACTIVE_MODE # Use the global flag set in main

    norm_input_artist_match_str, input_artist_has_live_format = normalize_and_detect_specific_live_format(input_artist)
    norm_input_title_match_str, input_title_has_live_format = normalize_and_detect_specific_live_format(input_track)
    is_input_explicitly_live_format = input_artist_has_live_format or input_title_has_live_format

    logging.debug(f"BEGIN SEARCH (Interactive: {INTERACTIVE_MODE}): For Input='{input_artist} - {input_track}' (InputLiveFmt: {is_input_explicitly_live_format})")
    logging.debug(f"  Norm Input Match: Artist='{norm_input_artist_match_str}', Title='{norm_input_title_match_str}'")

    # --- Find initial artist candidates ---
    candidate_artist_entries = []
    processed_artists_for_debug = set()
    best_artist_substring_miss_entry, best_artist_substring_miss_score = None, -1

    for entry in library_index:
        norm_library_artist_stripped = entry["norm_artist_stripped"]
        # Substring match (prefer this)
        if norm_input_artist_match_str and norm_library_artist_stripped and norm_input_artist_match_str in norm_library_artist_stripped:
            candidate_artist_entries.append(entry)
            if norm_library_artist_stripped not in processed_artists_for_debug:
                logging.debug(f"  Artist Substring Candidate: Input '{norm_input_artist_match_str}' in Lib Artist '{norm_library_artist_stripped}' (Path: {entry['path']})")
                processed_artists_for_debug.add(norm_library_artist_stripped)
        # Empty artist matches empty artist
        elif not norm_input_artist_match_str and not norm_library_artist_stripped:
             candidate_artist_entries.append(entry)
             if "UNKNOWN_ARTIST_EMPTY_INPUT" not in processed_artists_for_debug:
                 logging.debug(f"  Artist Empty Match: Path: {entry['path']}")
                 processed_artists_for_debug.add("UNKNOWN_ARTIST_EMPTY_INPUT")
        # Track fuzzy misses for logging
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
        # If interactive, prompt user (only Skip available)
        if INTERACTIVE_MODE:
             print(colorize(f"\nNo potential artists found containing '{input_artist}'.", Colors.YELLOW))
             return prompt_user_for_choice(input_artist, input_track, [], [], is_input_explicitly_live_format, match_threshold) # No candidates, no artist matches
        else:
             return None

    logging.info(f"Found {len(candidate_artist_entries)} entries potentially matching artist '{input_artist}'. Matching title '{input_track}'.")

    # --- Score all potential title matches for the found artists ---
    scored_candidates = [] # List to hold qualified candidates' dictionaries
    all_title_misses = [] # Store tuples: (final_score, entry_dict)

    for entry in candidate_artist_entries:
        title_meta_score = fuzz.ratio(norm_input_title_match_str, entry["norm_title_stripped"]) if entry["norm_title_stripped"] else -1
        filename_score_for_title = fuzz.token_set_ratio(norm_input_title_match_str, entry["norm_filename_stripped"])
        logging.debug(f"  Testing entry '{Path(entry['path']).name}' (Live: {entry['entry_is_live']}): TitleScore={title_meta_score}, FilenameScore={filename_score_for_title}")

        current_base_score = max(title_meta_score, filename_score_for_title)

        # Consider slightly below threshold to allow bonuses/penalties
        if current_base_score >= (match_threshold - 15) :
             adjusted_score = current_base_score
             if entry["norm_artist_stripped"] == norm_input_artist_match_str:
                 artist_bonus = 1.0
             else:
                 library_artist_match_to_input_artist = fuzz.ratio(norm_input_artist_match_str, entry["norm_artist_stripped"])
                 artist_bonus = (library_artist_match_to_input_artist / 100.0) * 1.5
             adjusted_score += artist_bonus
             adjusted_score = min(adjusted_score, 100.0)

             original_score_before_penalty = adjusted_score
             penalty_applied = False
             if not is_input_explicitly_live_format and entry["entry_is_live"]:
                 adjusted_score *= live_penalty_factor
                 penalty_applied = True
                 logging.debug(f"      Applied Penalty: {original_score_before_penalty:.1f} * {live_penalty_factor} -> {adjusted_score:.1f}")

             entry['_current_score_before_prompt'] = adjusted_score
             entry['_original_score'] = original_score_before_penalty
             entry['_penalty_applied'] = penalty_applied

             # Store all evaluated candidates initially
             scored_candidates.append(entry)
             # We filter based on threshold later before deciding mode

        else:
            all_title_misses.append((current_base_score, entry)) # Track low base scores too
            logging.debug(f"    Candidate Base Score Too Low (Base: {current_base_score:.1f}, Path: {entry['path']})")

    # --- Filter and Decide Action ---

    # Keep only candidates meeting threshold *after* scoring/penalty
    qualified_candidates = [c for c in scored_candidates if c.get('_current_score_before_prompt', -1) >= match_threshold]
    qualified_candidates.sort(key=lambda x: x.get('_current_score_before_prompt', -1), reverse=True)

    if not qualified_candidates:
        # No candidates met the final threshold
        log_msg = f"NO MATCH: No tracks found for '{input_artist} - {input_track}' meeting threshold {match_threshold} after scoring."
        # Log the best overall miss (from *all* candidates attempted)
        all_misses_combined = all_title_misses + [ (c['_current_score_before_prompt'], c) for c in scored_candidates if c not in qualified_candidates ]
        if all_misses_combined:
            all_misses_combined.sort(key=lambda x: x[0], reverse=True)
            best_miss_score, best_miss_entry = all_misses_combined[0]
            log_msg += (f"\n     -> Closest Miss: '{best_miss_entry['artist']} - {best_miss_entry['title']}' (Final Score: {best_miss_score:.1f}, Path: {best_miss_entry['path']})")
        logging.warning(log_msg)

        if INTERACTIVE_MODE:
            print(colorize(f"\nNo direct match found meeting threshold for '{input_artist} - {input_track}'.", Colors.YELLOW))
            # Pass *all* scored candidates (even below threshold) for potential display context, but prompt handles filtering
            return prompt_user_for_choice(input_artist, input_track, scored_candidates, candidate_artist_entries, is_input_explicitly_live_format, match_threshold)
        else:
            return None

    # We have at least one QUALIFIED candidate

    # If NOT interactive OR only ONE qualified candidate: Use automatic logic
    if not INTERACTIVE_MODE or len(qualified_candidates) == 1:
         logging.debug("Using Automatic/Single Qualified Candidate Logic.")
         best_live_candidate = next((c for c in qualified_candidates if c['entry_is_live']), None)
         best_non_live_candidate = next((c for c in qualified_candidates if not c['entry_is_live']), None)
         best_overall_match = qualified_candidates[0] # Default to absolute best score

         if is_input_explicitly_live_format:
             if best_live_candidate: best_overall_match = best_live_candidate
             elif best_non_live_candidate:
                 logging.warning(f"AUTO/SINGLE: Input Live, only Studio found/selected: {best_non_live_candidate['path']} (Score: {best_non_live_candidate['_current_score_before_prompt']:.1f})")
                 best_overall_match = best_non_live_candidate
         else: # Input not live
             if best_non_live_candidate:
                 best_overall_match = best_non_live_candidate
                 if best_live_candidate and best_live_candidate['_current_score_before_prompt'] > best_non_live_candidate['_current_score_before_prompt'] + 5:
                     logging.warning(f"AUTO/SINGLE: Studio input, but LIVE higher post-penalty. OVERRIDING: {best_live_candidate['path']} ({best_live_candidate['_current_score_before_prompt']:.1f} vs {best_non_live_candidate['_current_score_before_prompt']:.1f})")
                     best_overall_match = best_live_candidate
             elif best_live_candidate:
                 logging.warning(f"AUTO/SINGLE: Input Studio, only Live found/selected: {best_live_candidate['path']} (Score: {best_live_candidate['_current_score_before_prompt']:.1f})")
                 best_overall_match = best_live_candidate

         final_score = best_overall_match['_current_score_before_prompt']
         logging.info(f"MATCHED (Auto/Single): '{input_artist} - {input_track}' -> '{best_overall_match['path']}' Score: {final_score:.1f}")
         best_overall_match.pop('_current_score_before_prompt', None)
         best_overall_match.pop('_original_score', None)
         best_overall_match.pop('_penalty_applied', None)
         return best_overall_match

    else: # Interactive mode AND multiple QUALIFIED candidates
        logging.info(f"INTERACTIVE: Multiple ({len(qualified_candidates)}) qualified candidates found for '{input_artist} - {input_track}'. Prompting user.")
        chosen_entry = prompt_user_for_choice(
            input_artist=input_artist,
            input_track=input_track,
            candidates=qualified_candidates, # Pass only those meeting threshold
            artist_matches=candidate_artist_entries, # Full list for random
            input_live_format=is_input_explicitly_live_format,
            threshold=match_threshold
        )
        if chosen_entry: # Clean up temp keys if user didn't skip
            chosen_entry.pop('_current_score_before_prompt', None)
            chosen_entry.pop('_original_score', None)
            chosen_entry.pop('_penalty_applied', None)
        return chosen_entry # Can be dict or None

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
def generate_playlist(tracks, input_playlist_path, output_dir_str, mpd_playlist_dir_str, mpd_music_dir_str, match_threshold, log_file_path_obj, missing_tracks_dir_path, live_penalty_factor):
    """Generates the M3U playlist, handling matching and output."""
    global library_index
    if not library_index: # Check again before processing
        logging.error("Library index is empty. Cannot generate playlist.")
        print(colorize("Error: Music library index is empty. Cannot generate playlist.", Colors.RED), file=sys.stderr)
        return

    try:
        resolved_mpd_music_dir = Path(mpd_music_dir_str).resolve(strict=True)
        logging.info(f"Using resolved MPD music directory: {resolved_mpd_music_dir}")
    except FileNotFoundError:
        logging.error(f"MPD music directory does not exist: '{mpd_music_dir_str}'.")
        print(colorize(f"Error: MPD music directory '{mpd_music_dir_str}' not found. Check config/args.", Colors.RED), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error resolving MPD music directory '{mpd_music_dir_str}': {e}")
        print(colorize(f"Error resolving MPD music directory: {e}", Colors.RED), file=sys.stderr)
        sys.exit(1)

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

            except ValueError as ve:
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
            # Specific logging for the skip reason is handled within find_track_in_index or prompt

    # --- Filename Generation & Writing ---
    input_path_obj = Path(input_playlist_path)
    base_name_no_ext = input_path_obj.stem
    # Sanitize for filename - replace multiple non-alphanum chars with single underscore
    sanitized_base = re.sub(r'[^a-zA-Z0-9]+', '_', base_name_no_ext).strip('_')
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_filename = f"{sanitized_base}_{date_str}.m3u" if sanitized_base else f"playlist_{date_str}.m3u" # Fallback name

    output_dir = Path(output_dir_str) # Already resolved in main
    try:
        output_dir.mkdir(parents=True, exist_ok=True) # Ensure output dir exists
        output_m3u_path = output_dir / output_filename
        with open(output_m3u_path, "w", encoding="utf-8") as f:
            f.write("\n".join(m3u_lines) + "\n") # Ensure trailing newline
        print(f"\n{colorize('Generated playlist', Colors.GREEN + Colors.BOLD)} ({found_count}/{total_tracks} tracks included): {output_m3u_path}")
        logging.info(f"Generated playlist '{output_m3u_path}' with {found_count} of {total_tracks} input tracks.")
    except Exception as e:
        logging.error(f"Failed to write playlist to {output_m3u_path}: {e}", exc_info=True)
        print(colorize(f"Error writing output playlist {output_m3u_path}: {e}", Colors.RED), file=sys.stderr)
        return # Stop if primary output fails

    # --- Optionally copy to MPD playlist directory ---
    if mpd_playlist_dir_str:
        try:
            mpd_playlist_dir = Path(mpd_playlist_dir_str) # Already resolved
            if not mpd_playlist_dir.is_dir():
                if not mpd_playlist_dir.exists():
                    logging.info(f"MPD playlist directory '{mpd_playlist_dir}' does not exist. Creating.")
                    mpd_playlist_dir.mkdir(parents=True, exist_ok=True)
                else:
                    logging.error(f"MPD playlist path '{mpd_playlist_dir}' exists but is not a directory.")
                    raise FileNotFoundError(f"Not a directory: {mpd_playlist_dir}")

            mpd_m3u_path = mpd_playlist_dir / output_filename
            with open(mpd_m3u_path, "w", encoding="utf-8") as f:
                f.write("\n".join(m3u_lines) + "\n")
            print(f"{colorize('Copied playlist to MPD directory:', Colors.CYAN)} {mpd_m3u_path}")
            logging.info(f"Copied playlist to MPD directory: {mpd_m3u_path}")
        except (FileNotFoundError, PermissionError, OSError, Exception) as e:
            logging.error(f"Failed to copy playlist to MPD directory '{mpd_playlist_dir_str}': {e}", exc_info=True)
            print(colorize(f"Warning: Failed to copy playlist to MPD directory '{mpd_playlist_dir_str}': {e}", Colors.YELLOW), file=sys.stderr)

    # --- Write Missing Tracks File ---
    if skipped_track_inputs:
        try:
            missing_tracks_dir_path.mkdir(parents=True, exist_ok=True)
            missing_filename_base = f"{sanitized_base}_{date_str}" if sanitized_base else f"playlist_{date_str}"
            missing_filename = f"{missing_filename_base}-missing-tracks.txt"
            missing_file_path = missing_tracks_dir_path / missing_filename
            with open(missing_file_path, "w", encoding="utf-8") as f_missing:
                f_missing.write(f"# Input playlist: {input_playlist_path}\n")
                f_missing.write(f"# Generated M3U: {output_m3u_path}\n")
                f_missing.write(f"# Date Generated: {datetime.now().isoformat()}\n")
                f_missing.write(f"# {len(skipped_track_inputs)} tracks from input file not found or skipped:\n")
                f_missing.write("-" * 30 + "\n")
                for missing_track_info in skipped_track_inputs:
                    f_missing.write(f"{missing_track_info}\n")
            print(f"{colorize('List of missing/skipped tracks saved to:', Colors.YELLOW)} {missing_file_path}")
            logging.info(f"List of {len(skipped_track_inputs)} missing/skipped tracks saved to: {missing_file_path}")
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

# --- Main Execution ---
def main(argv_list=None): # Can accept arguments for GUI usage
    global INTERACTIVE_MODE
    global PARENTHETICAL_STRIP_REGEX
    global config

    # --- Determine Script Directory ---
    script_dir = Path.cwd() # Default if __file__ fails
    try:
        script_dir = Path(__file__).parent.resolve()
    except NameError:
        pass # Keep CWD

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
    # Use f-strings to show default values in help text
    parser = argparse.ArgumentParser(
        description=f"{Colors.BOLD}Generate M3U playlists by matching 'Artist - Track' lines against a music library.{Colors.RESET}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Set defaults to None to detect if they were set via command line
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
    parser.add_argument("--log-file", type=Path, default=None, help=f"Log file path. Cfg: Logging.log_file, Def: <script_dir>/{DEFAULT_LOG_FILE_NAME}")
    parser.add_argument("--log-mode", choices=['append', 'overwrite'], default=None, help="Log file mode. Cfg: Logging.log_mode, Def: overwrite")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=None, help="Log level for file. Cfg: Logging.log_level, Def: INFO")
    parser.add_argument("-e", "--extensions", nargs='+', default=None, help=f"Audio extensions. Cfg: General.extensions, Def: {' '.join(DEFAULT_SUPPORTED_EXTENSIONS)}")
    parser.add_argument("--live-album-keywords", nargs='+', default=None, help="Regex patterns for live albums. Cfg: Matching.live_album_keywords")
    parser.add_argument("--strip-keywords", nargs='+', default=None, help="Keywords to strip from (). Cfg: Matching.strip_keywords")
    parser.add_argument("-i", "--interactive", action="store_true", default=None, help="Enable interactive mode. Cfg: General.interactive, Def: false")

    # --- Argument Parser Setup (inside main as before) ---
    # ...
    if argv_list is None: # Running from command line
        args = parser.parse_args()
    else: # Called with specific args (e.g., from GUI)
        args = parser.parse_args(argv_list)

    # --- Determine Final Configuration Values ---
    final_library_path = args.library if args.library is not None else get_config("Paths", "library", DEFAULT_SCAN_LIBRARY)
    final_mpd_music_dir = args.mpd_music_dir if args.mpd_music_dir is not None else get_config("Paths", "mpd_music_dir", DEFAULT_MPD_MUSIC_DIR_CONF)
    final_output_dir = args.output_dir if args.output_dir is not None else get_config("Paths", "output_dir", DEFAULT_OUTPUT_DIR)
    final_missing_dir = args.missing_dir if args.missing_dir is not None else get_config("Paths", "missing_dir", DEFAULT_MISSING_TRACKS_DIR)

    # MPD Playlist Dir Logic
    final_mpd_playlist_dir = None
    if args.mpd_playlist_dir is not None: # Flag used
        if args.mpd_playlist_dir == "USE_DEFAULT_OR_CONFIG": # Flag used w/o value
             config_val = get_config("Paths", "mpd_playlist_dir", fallback="USE_DEFAULT_CONST")
             if config_val == "USE_DEFAULT_CONST": final_mpd_playlist_dir = DEFAULT_MPD_PLAYLIST_DIR_CONF
             elif config_val: final_mpd_playlist_dir = config_val
             else: final_mpd_playlist_dir = None # Explicitly disabled in config
        else: final_mpd_playlist_dir = args.mpd_playlist_dir # Flag used w/ value
    else: # Flag not used
        config_val = get_config("Paths", "mpd_playlist_dir", fallback=None)
        final_mpd_playlist_dir = config_val if config_val else None

    final_threshold = args.threshold if args.threshold is not None else get_config("Matching", "threshold", DEFAULT_MATCH_THRESHOLD, int)
    final_live_penalty = args.live_penalty if args.live_penalty is not None else get_config("Matching", "live_penalty", DEFAULT_LIVE_PENALTY_FACTOR, float)
    final_live_album_kws = args.live_album_keywords if args.live_album_keywords is not None else get_config("Matching", "live_album_keywords", DEFAULT_LIVE_ALBUM_KEYWORDS, list)
    final_strip_keywords = args.strip_keywords if args.strip_keywords is not None else get_config("Matching", "strip_keywords", DEFAULT_PARENTHETICAL_STRIP_KEYWORDS, list)

    # Log File Path
    default_log_path = script_dir / DEFAULT_LOG_FILE_NAME
    config_log_file_str = get_config("Logging", "log_file", str(default_log_path))
    final_log_file_path = args.log_file if args.log_file is not None else Path(config_log_file_str)

    final_log_mode = args.log_mode if args.log_mode is not None else get_config("Logging", "log_mode", "overwrite")
    final_log_level_str = args.log_level if args.log_level is not None else get_config("Logging", "log_level", "INFO")

    final_extensions = args.extensions if args.extensions is not None else get_config("General", "extensions", DEFAULT_SUPPORTED_EXTENSIONS, list)

    if args.interactive is True: # Check explicitly for True (set by store_true)
         final_interactive = True
    elif args.interactive is None: # Check if flag was NOT used
         final_interactive = get_config("General", "interactive", fallback=False, expected_type=bool)
    else: # Should not happen with store_true, but safety fallback
        final_interactive = False

    # Set Global flag
    INTERACTIVE_MODE = final_interactive

    # --- Expand User Paths ---
    final_library_path = os.path.expanduser(final_library_path)
    final_mpd_music_dir = os.path.expanduser(final_mpd_music_dir)
    final_output_dir = os.path.expanduser(final_output_dir)
    final_missing_dir = os.path.expanduser(final_missing_dir)
    if final_mpd_playlist_dir: final_mpd_playlist_dir = os.path.expanduser(final_mpd_playlist_dir)
    # Resolve log path *after* expansion
    try:
        final_log_file_path = Path(os.path.expanduser(str(final_log_file_path))).resolve()
    except Exception as e:
         print(f"{Colors.YELLOW}Warning:{Colors.RESET} Could not fully resolve log path '{final_log_file_path}': {e}", file=sys.stderr)
         # Use the expanded path without resolve if resolve fails
         final_log_file_path = Path(os.path.expanduser(str(final_log_file_path)))

    # --- Post-processing / Validation ---
    if not (0 <= final_threshold <= 100): parser.error(f"--threshold ({final_threshold}) must be between 0 and 100.")
    if not (0.0 <= final_live_penalty <= 1.0): parser.error(f"--live-penalty ({final_live_penalty}) must be between 0.0 and 1.0.")
    final_supported_extensions = tuple(ext.lower() if ext.startswith('.') else '.' + ext.lower() for ext in final_extensions if ext) # Ensure non-empty

    # --- Setup Logging ---
    setup_logging(final_log_file_path, final_log_mode)
    log_level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    final_log_level = log_level_map.get(final_log_level_str.upper(), logging.INFO)
    logging.getLogger().setLevel(final_log_level)

    # --- Log Effective Settings ---
    logging.info("="*30 + " Playlist Maker Started " + "="*30)
    logging.info(f"Version: 1.6 (Config File & Color Output Final)")
    logging.info(f"Config files loaded: {loaded_files if loaded_files else 'None found'}")
    logging.info(f"--- Effective Settings ---")
    logging.info(f"  Interactive Mode: {final_interactive}")
    logging.info(f"  Input Playlist File: {args.playlist_file}")
    logging.info(f"  Library Scan Path: {final_library_path}")
    logging.info(f"  MPD Music Dir: {final_mpd_music_dir}")
    logging.info(f"  Output Dir: {final_output_dir}")
    logging.info(f"  Missing Tracks Dir: {final_missing_dir}")
    logging.info(f"  MPD Playlist Copy Dir: {final_mpd_playlist_dir if final_mpd_playlist_dir else 'Disabled'}")
    logging.info(f"  Match Threshold: {final_threshold}")
    logging.info(f"  Live Penalty Factor: {final_live_penalty}")
    logging.info(f"  Log File: {final_log_file_path}")
    logging.info(f"  Log Mode: {final_log_mode}")
    logging.info(f"  Log Level: {final_log_level_str}")
    logging.info(f"  Supported Extensions: {final_supported_extensions}")
    logging.info(f"  Live Album Keywords: {final_live_album_kws}")
    logging.info(f"  Parenthetical Strip Keywords: {final_strip_keywords}")
    logging.info(f"--------------------------")

    # --- Compile Regex ---
    try:
        live_album_keywords_regex = None
        if final_live_album_kws:
             live_album_regex_pattern = r"(" + "|".join(final_live_album_kws) + r")"
             live_album_keywords_regex = re.compile(live_album_regex_pattern, re.IGNORECASE)
             logging.info(f"Using live album regex: {live_album_regex_pattern}")

        # Reset strip regex global before compiling
        PARENTHETICAL_STRIP_REGEX = None
        if final_strip_keywords:
            # Match keyword potentially surrounded by non-word chars or start/end
            strip_keywords_pattern = r"|".join(r"(?:\W|^)" + re.escape(kw) + r"(?:\W|$)" for kw in final_strip_keywords)
            PARENTHETICAL_STRIP_REGEX = re.compile(strip_keywords_pattern, re.IGNORECASE)
            logging.info(f"Using parenthetical strip regex: {strip_keywords_pattern}")

    except re.error as e:
        logging.error(f"Invalid regex pattern derived from config/defaults: {e}")
        print(colorize(f"Error: Invalid regex pattern in keywords: {e}", Colors.RED), file=sys.stderr)
        sys.exit(1)

    # --- Resolve/Check remaining paths ---
    missing_tracks_dir_resolved = Path(final_missing_dir).resolve()
    try:
        playlist_file_abs = Path(args.playlist_file).resolve(strict=True)
        library_abs = Path(final_library_path).resolve(strict=True)
        mpd_music_dir_abs = Path(final_mpd_music_dir).resolve(strict=True)
        output_dir_abs = Path(final_output_dir).resolve()
        logging.info(f"Resolved Input Playlist: {playlist_file_abs}")
        # (Already logged library, mpd, output dirs)
    except FileNotFoundError as e:
        logging.error(f"Essential path does not exist after resolving: {e}. Exiting.")
        print(colorize(f"Error: Essential path not found: {e}", Colors.RED), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error resolving final paths: {e}", exc_info=True)
        print(colorize(f"Error resolving paths: {e}", Colors.RED), file=sys.stderr)
        sys.exit(1)

    # --- Main Execution Flow ---
    print(f"Reading input file: {args.playlist_file}...")
    tracks = read_playlist_file(args.playlist_file)
    if not tracks:
        logging.error("Exiting: No valid track entries read.")
        print(colorize(f"Error: No valid 'Artist - Track' lines found in '{args.playlist_file}'.", Colors.RED), file=sys.stderr)
        sys.exit(1)
    print(f"Read {len(tracks)} track entries.")

    scan_library(str(library_abs), final_supported_extensions, live_album_keywords_regex)
    if not library_index:
        # Error logged in scan_library
        sys.exit(1) # Exit if scan yielded nothing
    print(colorize(f"Scan complete. Found {len(library_index)} tracks in library index.", Colors.GREEN))

    generate_playlist(
        tracks=tracks,
        input_playlist_path=str(playlist_file_abs), # Pass absolute path
        output_dir_str=str(output_dir_abs),
        mpd_playlist_dir_str=str(final_mpd_playlist_dir) if final_mpd_playlist_dir else None,
        mpd_music_dir_str=str(mpd_music_dir_abs),
        match_threshold=final_threshold,
        log_file_path_obj=final_log_file_path,
        missing_tracks_dir_path=missing_tracks_dir_resolved,
        live_penalty_factor=final_live_penalty
    )

    logging.info("Playlist Maker script finished successfully.")
    print(f"\n{colorize('Done.', Colors.BOLD + Colors.GREEN)}")

    return True # Or some status object/dict

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