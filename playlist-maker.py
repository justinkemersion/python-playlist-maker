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

# --- Configuration (Defaults, overridden by argparse) ---
DEFAULT_SCAN_LIBRARY = os.path.expanduser("~/music")
DEFAULT_MPD_MUSIC_DIR_CONF = os.path.expanduser("~/music")
DEFAULT_MPD_PLAYLIST_DIR_CONF = os.path.expanduser("~/.config/mpd/playlists")
DEFAULT_OUTPUT_DIR = "./playlists"
DEFAULT_MISSING_TRACKS_DIR = "./missing-tracks"
DEFAULT_LOG_FILE = "warning.log"
DEFAULT_SUPPORTED_EXTENSIONS = (".mp3", ".flac", ".ogg", ".m4a")
DEFAULT_MATCH_THRESHOLD = 75
DEFAULT_LIVE_PENALTY_FACTOR = 0.75
DEFAULT_LIVE_ALBUM_KEYWORDS = [
    r'\blive\b', r'\bunplugged\b', r'\bconcert\b', r'live at', r'live in', r'live from',
    r'official bootleg', r'acoustic sessions', r'peel session[s]?', r'radio session[s]?',
    r'mtv unplugged'
]
# <<< Keywords to potentially strip from parentheses during normalization >>>
DEFAULT_PARENTHETICAL_STRIP_KEYWORDS = [
    r'remix', r'radio edit', r'edit', r'version', r'mix', r'acoustic',
    r'mono', r'stereo', r'reprise', r'instrumental'
]


try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path.cwd()
DEFAULT_LOG_FILE = SCRIPT_DIR / "warning.log"

library_index = []
INTERACTIVE_MODE = False # Global flag for interactivity, set in main()
PARENTHETICAL_STRIP_REGEX = None # Compiled regex for stripping parenthetical keywords

# <<< ENHANCED NORMALIZATION FUNCTIONS >>>
def normalize_and_detect_specific_live_format(s):
    """
    Normalizes a string for matching (handling '&', '/', 'and', feat., common suffixes in parens)
    and specifically detects if it contains '(live)' format in the original casing structure.
    Returns normalized string for matching and a boolean for live detection.
    """
    global PARENTHETICAL_STRIP_REGEX # Use the compiled regex

    if not isinstance(s, str): return "", False

    original_s_lower_for_live_check = s.lower() # Use lowercase original for reliable live check

    # --- Live Detection (on minimally processed string) ---
    is_live_format = bool(re.search(r'\(\s*live[\s\W]*\)', original_s_lower_for_live_check, re.IGNORECASE))
    # Logging handled later if debug is needed

    # --- String Preparation for Matching ---
    try:
        normalized_s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    except TypeError:
        (logging.warning if logging.getLogger().hasHandlers() else print)(f"Normalization failed for non-string input: {s}")
        return "", False # Return default for failure

    s_for_matching = normalized_s.lower()
    logging.debug(f"Norm Step 1 (Input='{s}'): NFD+Lower='{s_for_matching}' | LiveFormatDetected={is_live_format}")

    # Replace '&', '/', 'and' with spaces
    s_for_matching = re.sub(r'\s*&\s*', ' ', s_for_matching)
    s_for_matching = re.sub(r'\s*/\s*', ' ', s_for_matching)
    s_for_matching = re.sub(r'\s+and\s+', ' ', s_for_matching)
    logging.debug(f"Norm Step 2: Replace '&/and' -> '{s_for_matching}'")

    # Strip track numbers from the beginning
    s_for_matching = re.sub(r'^\s*\d{1,3}[\s.-]+\s*', '', s_for_matching).strip()
    logging.debug(f"Norm Step 3: Strip TrackNum -> '{s_for_matching}'")

    # Function to intelligently handle parenthetical content for matching
    def process_parenthetical_content(match):
        content = match.group(1).strip().lower()
        logging.debug(f"Norm Step 4a: Examining Parenthesis Content: '{content}'")

        # Keep '(live)' variations specifically
        if re.fullmatch(r'live[\s\W]*', content, re.IGNORECASE):
            logging.debug(f"  -> Keeping 'live' token.")
            return ' live ' # Return space-padded 'live' token

        # Keep '(feat...)' variations, normalize content inside
        feat_match = re.match(r'(?:feat|ft|featuring|with)\.?\s*(.*)', content, re.IGNORECASE)
        if feat_match:
            feat_artist = feat_match.group(1).strip()
            # Basic normalization for the featured artist part
            feat_artist_norm = ''.join(c for c in feat_artist if c.isalnum() or c.isspace())
            feat_artist_norm = re.sub(r'\s+', ' ', feat_artist_norm).strip()
            logging.debug(f"  -> Keeping 'feat' token with normalized artist: 'feat {feat_artist_norm}'")
            return f' feat {feat_artist_norm} ' # Return space-padded 'feat artist'

        # Remove common suffixes if they appear alone or primarily within the parenthesis
        # Use the pre-compiled regex PARENTHETICAL_STRIP_REGEX
        if PARENTHETICAL_STRIP_REGEX and PARENTHETICAL_STRIP_REGEX.fullmatch(content):
             logging.debug(f"  -> Removing common suffix/term found in parenthesis: '{content}'")
             return '' # Remove these common terms

        # Default: Remove other parenthetical content for matching string
        logging.debug(f"  -> Removing generic parenthesis content.")
        return ''

    # Apply parenthetical processing
    s_for_matching = re.sub(r'\(([^)]*)\)', process_parenthetical_content, s_for_matching)
    logging.debug(f"Norm Step 4b: After Parenthesis Processing -> '{s_for_matching}'")

    # Final cleanup: keep only alphanumerics and spaces, collapse multiple spaces
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

    # Normalize using the standard function to ensure consistency
    normalized_album_for_check, album_has_specific_live_format = normalize_and_detect_specific_live_format(album_title_str)

    # Check against regex keywords
    if live_keywords_regex.search(normalized_album_for_check):
        logging.debug(f"Album '{album_title_str}' (normalized: '{normalized_album_for_check}') matched live indicator regex.")
        return True

    # Check specific '(live)' format detected during normalization
    if album_has_specific_live_format:
        logging.debug(f"Album '{album_title_str}' detected specific '(live)' format during normalization.")
        return True

    return False

def setup_logging(log_file_path, log_mode):
    # (Unchanged from previous version)
    filemode = 'a' if log_mode == 'append' else 'w'
    log_file_str = ""
    try:
        log_parent_dir = log_file_path.parent
        log_parent_dir.mkdir(parents=True, exist_ok=True)
        log_file_str = str(log_file_path)
    except Exception as e:
        print(f"Warning: Could not create directory for log file {log_file_path}: {e}", file=sys.stderr)
        try:
            log_file_path = Path.cwd() / log_file_path.name; log_file_str = str(log_file_path)
            print(f"Attempting to log to fallback path: {log_file_str}", file=sys.stderr)
        except Exception as fallback_e: print(f"ERROR: Could not even determine fallback log path: {fallback_e}", file=sys.stderr); return
    if not os.access(Path(log_file_str).parent, os.W_OK): print(f"ERROR: No write permission for log directory: {Path(log_file_str).parent}", file=sys.stderr); return
    for handler in logging.root.handlers[:]: logging.root.removeHandler(handler)
    try:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s", filename=log_file_str, filemode=filemode, force=True)
    except Exception as e: print(f"ERROR: Exception during logging.basicConfig: {e}", file=sys.stderr); return
    console_handler = logging.StreamHandler(sys.stderr); console_handler.setLevel(logging.WARNING)
    formatter = logging.Formatter('%(levelname)s: [%(funcName)s] %(message)s'); console_handler.setFormatter(formatter)
    logger = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers):
        logger.addHandler(console_handler)

def get_file_metadata(file_path_obj):
    # (Unchanged from previous version - relying on pandas dummy if needed)
    artist, title, album, duration = "", "", "", None # Initialize all to default/empty
    try:
        # Attempt to open the file with mutagen. Easy=True is for common tags.
        audio = mutagen.File(file_path_obj, easy=True)

        # Also open without easy=True to get detailed info, especially for duration.
        # This can sometimes succeed even if easy=True struggles or returns a less specific object.
        detailed_audio = mutagen.File(file_path_obj)

        if audio: # If easy=True loading was successful and returned an object
            # Get artist: Try 'artist', then 'albumartist', then 'performer' tags
            artist_tags = audio.get("artist", []) or \
                          audio.get("albumartist", []) or \
                          audio.get("performer", [])
            artist = artist_tags[0].strip() if artist_tags else "" # Take the first tag if multiple, strip whitespace

            # Get title
            title_tags = audio.get("title", [])
            title = title_tags[0].strip() if title_tags else ""

            # Get album
            album_tags = audio.get("album", [])
            album = album_tags[0].strip() if album_tags else ""

        # Get duration from the detailed_audio object, which is generally more reliable
        if detailed_audio and hasattr(detailed_audio, 'info') and hasattr(detailed_audio.info, 'length'):
            try:
                duration_float = float(detailed_audio.info.length) # Length is usually in seconds
                # Check if duration_float is NaN (Not a Number) or None before converting to int
                # pd.isna is a robust way if pandas is imported, otherwise use a simpler check.
                if not pd.isna(duration_float): # Handles None and float('nan')
                    duration = int(duration_float) # Convert to integer seconds
            except (ValueError, TypeError):
                # This catches if detailed_audio.info.length is not a number or None
                duration = None # Keep duration as None if conversion fails

        # <<< Logging for missing metadata (as added in previous response) >>>
        if not artist and audio: # Check 'audio' to ensure easy load was attempted
            logging.debug(f"Metadata: Artist tag empty/missing for {file_path_obj}")
        if not title and audio:
            logging.debug(f"Metadata: Title tag empty/missing for {file_path_obj}")
        # No specific debug log if album is empty, as it's less critical for basic matching

        if duration is None:
            if detailed_audio and hasattr(detailed_audio, 'info') and hasattr(detailed_audio.info, 'length'):
                 logging.debug(f"Metadata: Duration could not be determined for {file_path_obj} (info.length: {detailed_audio.info.length}, type: {type(detailed_audio.info.length).__name__})")
            elif detailed_audio and hasattr(detailed_audio, 'info') and not hasattr(detailed_audio.info, 'length'):
                logging.debug(f"Metadata: detailed_audio.info lacks 'length' attribute for {file_path_obj}")
            elif not detailed_audio:
                logging.debug(f"Metadata: detailed_audio object itself is None or failed to load for {file_path_obj}")
            else: # General case if other conditions didn't catch why duration is None
                logging.debug(f"Metadata: Duration is None for {file_path_obj} for an undetermined reason within metadata reading.")


    except mutagen.MutagenError as me:
        # Specific error for Mutagen issues (e.g., file format not supported, corrupt file for mutagen)
        logging.debug(f"Mutagen specific error processing metadata for {file_path_obj}: {me}")
    except Exception as e:
        # Catch any other unexpected errors during metadata extraction.
        # Avoid logging very common errors if they are not critical for core functionality.
        # For instance, some files might not be parseable by easy=True but detailed_audio might still get duration.
        # The current structure tries to get as much as possible.
        # Log with exc_info=True to get the full traceback for unexpected issues.
        logging.warning(f"Could not read metadata for {file_path_obj} due to {type(e).__name__}: {e}", exc_info=False) # Keep exc_info False for now unless debugging specific files
        # Ensure defaults are returned if an error occurs high up
        artist, title, album, duration = artist or "", title or "", album or "", duration or None

    return artist, title, album, duration

def scan_library(scan_library_path_str, supported_extensions, live_album_keywords_regex):
    # (Largely unchanged, uses new normalization implicitly)
    global library_index
    library_index = []
    try:
        scan_library_path = Path(scan_library_path_str).expanduser().resolve(strict=True)
    except FileNotFoundError:
        logging.error(f"Scan library path does not exist: {scan_library_path_str}")
        print(f"Error: Scan library path does not exist: {scan_library_path_str}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error resolving scan library path {scan_library_path_str}: {e}")
        print(f"Error: Could not resolve scan library path {scan_library_path_str}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning music library at {scan_library_path}..."); logging.info(f"Starting library scan at {scan_library_path}")
    start_time = time.time()
    processed_count = 0

    for root, _, files in os.walk(scan_library_path, followlinks=True):
        root_path = Path(root)
        for file in files:
            if file.lower().endswith(supported_extensions):
                processed_count += 1
                if processed_count % 500 == 0: print(".", end="", flush=True)

                file_path = root_path / file
                try:
                    if not os.access(file_path, os.R_OK):
                        logging.warning(f"Skipping inaccessible file during scan: {file_path}")
                        continue

                    abs_file_path = file_path.resolve()
                    meta_artist, meta_title, meta_album, meta_duration = get_file_metadata(abs_file_path)

                    # Use enhanced normalization here
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
                        "entry_is_live": current_entry_is_live # Consolidated live flag
                    })
                except OSError as e:
                    logging.warning(f"OS error processing file during scan {file_path}: {e}. Skipping.")
                except Exception as e:
                    logging.error(f"Unexpected error processing file during scan {file_path}: {e}", exc_info=True)

    print("\nScan complete.")
    end_time = time.time()
    logging.info(f"Library scan finished. Found {len(library_index)} tracks in {end_time - start_time:.2f} seconds.")
    if not library_index:
        logging.warning("Library scan resulted in 0 recognized tracks.")
        print("Warning: No tracks found in the specified scan library.", file=sys.stderr)


# <<< NEW: INTERACTIVE PROMPT FUNCTION >>>
def prompt_user_for_choice(input_artist, input_track, candidates, artist_matches, input_live_format, threshold):
    """
    Presents choices to the user for ambiguous matches or substitutions.

    Args:
        input_artist: The original artist string from the input file.
        input_track: The original track string from the input file.
        candidates: List of potential match dictionaries (scored, with 'entry_is_live', etc.).
                    Should be sorted by score descending BEFORE calling this.
        artist_matches: The list of all entries that matched the artist initially (for random selection).
        input_live_format: Boolean indicating if the input specifically asked for live.
        threshold: The matching threshold.

    Returns:
        The chosen entry dictionary, or None if the user chooses to skip.
    """
    print("-" * 70)
    print(f"INTERACTIVE PROMPT for:")
    print(f"  Input: {input_artist} - {input_track}")
    print(f"  (Input Specified Live: {input_live_format})")
    print("-" * 70)

    valid_choices = {}
    numeric_choice_counter = 1

    # --- Present numbered choices for direct candidates ---
    if candidates:
        print("Potential Matches Found (ranked by score):")
        # Limit displayed options to avoid overwhelming the user
        max_display = 7
        displayed_count = 0
        for entry in candidates:
             # Only display candidates above the original threshold for clarity, even if internal logic used slightly lower
             # Ensure score key exists before checking
             if entry.get('_current_score_before_prompt', -1) >= threshold:
                score = entry['_current_score_before_prompt']
                live_status = "LIVE" if entry['entry_is_live'] else "Studio"
                album_str = f" (Album: {entry.get('album', 'Unknown')})" if entry.get('album') else ""
                duration_str = f" [{entry['duration']}s]" if entry.get('duration', -1) != -1 else ""
                filename = Path(entry['path']).name # Get only the filename part

                # Highlight potential mismatches for the user
                live_mismatch_note = ""
                if input_live_format != entry['entry_is_live']:
                    live_mismatch_note = f" <-- NOTE: Live/Studio mismatch!" if not entry['_penalty_applied'] else f" <-- NOTE: Live/Studio mismatch (Penalty Applied)"

                print(f"  [{numeric_choice_counter}] {entry['artist']} - {entry['title']}{album_str}{duration_str}")
                print(f"      Score: {score:.1f} | Type: {live_status} | File: {filename}{live_mismatch_note}")

                valid_choices[str(numeric_choice_counter)] = entry
                numeric_choice_counter += 1
                displayed_count += 1
                if displayed_count >= max_display:
                    if len(candidates) > max_display:
                        print(f"      ... (and {len(candidates) - max_display} more candidates above threshold)")
                    break
        if displayed_count == 0:
             print("No matches found meeting the display threshold.")

    else:
        print("No direct title matches found meeting threshold.")

    # --- Present Substitution/Action choices ---
    print("\nChoose an action:")
    # Always offer Skip
    print("  [S]kip this track")
    valid_choices['s'] = None # Represents the 'skip' action

    # Offer Random only if there were initial artist matches
    can_offer_random = bool(artist_matches)
    random_entry = None # Placeholder for selected random entry
    if can_offer_random:
        print(f"  [R]andom track from library by artist containing '{input_artist}' (may have unrelated title)")
        valid_choices['r'] = 'random' # Special marker for the 'random' action

    # Provide context notes based on what was found
    found_live = any(c.get('entry_is_live', False) for c in candidates)
    found_studio = any(not c.get('entry_is_live', True) for c in candidates)

    if not input_live_format and found_live and not found_studio and candidates and displayed_count > 0:
         print("  NOTE: Input track seems Studio, only LIVE version(s) met threshold.")
    elif input_live_format and not found_live and found_studio and candidates and displayed_count > 0:
         print("  NOTE: Input track seems LIVE, only STUDIO version(s) met threshold.")
    elif candidates and found_live and found_studio and displayed_count > 0:
         print("  NOTE: Both Studio and LIVE versions found. Check types listed above.")

    # --- Get User Input ---
    while True:
        choice = input("Your choice (number, S, R): ").lower().strip()
        if choice in valid_choices:
            selected_option = valid_choices[choice]

            if selected_option == 'random':
                 # Execute the random choice logic
                 if artist_matches: # Should always be true if 'r' was a valid choice
                     random_entry = random.choice(artist_matches)
                     print(f"\nSelected Random Track:")
                     print(f"  Artist: {random_entry['artist']}")
                     print(f"  Title:  {random_entry['title']}")
                     print(f"  Path:   {random_entry['path']}")
                     logging.info(f"INTERACTIVE: User chose [R]andom track for '{input_artist} - {input_track}'. Selected: {random_entry['path']}")
                     return random_entry # Return the chosen random entry's dictionary
                 else:
                     # This case should ideally not be reached due to can_offer_random check
                     print("Error: No tracks found for this artist to pick randomly from.")
                     logging.warning(f"INTERACTIVE: User chose [R]andom for '{input_artist} - {input_track}', but no artist matches available unexpectedly.")
                     continue # Re-prompt the user

            elif selected_option is None:
                 # User chose to Skip
                 print("\nSkipping track.")
                 logging.info(f"INTERACTIVE: User chose [S]kip for '{input_artist} - {input_track}'.")
                 return None # Return None to indicate skipping
            else:
                 # User selected a specific numbered candidate
                 print(f"\nSelected Match [{choice}]:")
                 print(f"  Artist: {selected_option['artist']}")
                 print(f"  Title:  {selected_option['title']}")
                 print(f"  Path:   {selected_option['path']}")
                 logging.info(f"INTERACTIVE: User chose candidate [{choice}] for '{input_artist} - {input_track}'. Selected: {selected_option['path']}")
                 return selected_option # Return the chosen candidate's dictionary
        else:
            print(f"Invalid choice '{choice}'. Please enter a valid number from the list above, or S/R.")


# <<< MODIFIED find_track_in_index incorporating INTERACTIVE logic >>>
def find_track_in_index(input_artist, input_track, match_threshold, live_penalty_factor):
    global library_index
    global INTERACTIVE_MODE # Use the global flag

    # Use enhanced normalization
    norm_input_artist_match_str, input_artist_has_live_format = normalize_and_detect_specific_live_format(input_artist)
    norm_input_title_match_str, input_title_has_live_format = normalize_and_detect_specific_live_format(input_track)
    is_input_explicitly_live_format = input_artist_has_live_format or input_title_has_live_format

    logging.debug(f"BEGIN SEARCH (Interactive: {INTERACTIVE_MODE}): For Input='{input_artist} - {input_track}' (InputLiveFmt: {is_input_explicitly_live_format})")
    logging.debug(f"  Norm Input Match: Artist='{norm_input_artist_match_str}', Title='{norm_input_title_match_str}'")

    # --- Find initial artist candidates (Substring match first, then potentially fuzzy) ---
    candidate_artist_entries = []
    processed_artists_for_debug = set()
    best_artist_substring_miss_entry, best_artist_substring_miss_score = None, -1

    # Prefer substring match for artists initially
    for entry in library_index:
        norm_library_artist_stripped = entry["norm_artist_stripped"]
        # Check for non-empty strings before 'in' operation
        if norm_input_artist_match_str and norm_library_artist_stripped and norm_input_artist_match_str in norm_library_artist_stripped:
            candidate_artist_entries.append(entry)
            # Log unique artist matches for debugging
            if norm_library_artist_stripped not in processed_artists_for_debug:
                logging.debug(f"  Artist Substring Candidate: Input '{norm_input_artist_match_str}' in Lib Artist '{norm_library_artist_stripped}' (Path: {entry['path']})")
                processed_artists_for_debug.add(norm_library_artist_stripped)
        elif not norm_input_artist_match_str and not norm_library_artist_stripped: # Handle empty artist case
             candidate_artist_entries.append(entry)
             if "UNKNOWN_ARTIST_EMPTY_INPUT" not in processed_artists_for_debug:
                 logging.debug(f"  Artist Empty Match: Input artist empty, library artist empty. Will match on title. (Path: {entry['path']})")
                 processed_artists_for_debug.add("UNKNOWN_ARTIST_EMPTY_INPUT")
        else:
             # Track the best fuzzy miss among those *not* matching by substring
             if norm_input_artist_match_str and norm_library_artist_stripped: # Avoid fuzzy on empty strings
                current_artist_fuzzy_score = fuzz.ratio(norm_input_artist_match_str, norm_library_artist_stripped)
                if current_artist_fuzzy_score > best_artist_substring_miss_score:
                    best_artist_substring_miss_score = current_artist_fuzzy_score
                    best_artist_substring_miss_entry = entry

    if not candidate_artist_entries:
        # Log details if no substring match found
        miss_info = f"NO ARTIST MATCH: Input artist '{input_artist}' (Norm: '{norm_input_artist_match_str}') not found as substring in any library artist."
        if best_artist_substring_miss_entry:
             miss_info += (f"\n     -> Closest Fuzzy Artist Miss: '{best_artist_substring_miss_entry['artist']}' "
                           f"(Norm: '{best_artist_substring_miss_entry['norm_artist_stripped']}', "
                           f"Score: {best_artist_substring_miss_score}, Path: {best_artist_substring_miss_entry['path']})")
        logging.warning(miss_info)
        # In interactive mode, if no artist match, we could offer global search later, but for now, just offer Skip/Random based on *nothing*
        if INTERACTIVE_MODE:
             print(f"\nNo potential artists found containing '{input_artist}'.")
             # Cannot offer Random ('R') if candidate_artist_entries is empty. Only Skip ('S').
             return prompt_user_for_choice(input_artist, input_track, [], [], is_input_explicitly_live_format, match_threshold)
        else:
             return None # Automatic mode: No match

    logging.info(f"Found {len(candidate_artist_entries)} library entries potentially matching artist '{input_artist}'. Matching title '{input_track}'.")

    # --- Score all potential title matches for the found artists ---
    scored_candidates = [] # List to hold qualified candidates' dictionaries
    all_title_misses = [] # Store tuples: (raw_score, entry_dict) for logging misses

    for entry in candidate_artist_entries:
        # Use normalized fields for matching
        title_meta_score = fuzz.ratio(norm_input_title_match_str, entry["norm_title_stripped"]) if entry["norm_title_stripped"] else -1
        # Use token_set_ratio for filename - often better with extra words/numbers
        filename_score_for_title = fuzz.token_set_ratio(norm_input_title_match_str, entry["norm_filename_stripped"])

        logging.debug(f"  Testing entry '{Path(entry['path']).name}' (Live: {entry['entry_is_live']}): TitleScore={title_meta_score}, FilenameScore={filename_score_for_title}")

        # Take the better score between metadata title and filename stem
        current_base_score = max(title_meta_score, filename_score_for_title)

        # Only proceed with detailed scoring if the base score is promising
        # Consider slightly below threshold to allow bonuses/penalties to have effect
        if current_base_score >= (match_threshold - 15) :
             adjusted_score = current_base_score
             # Apply artist closeness bonus
             if entry["norm_artist_stripped"] == norm_input_artist_match_str:
                 artist_bonus = 1.0 # Small bonus for exact normalized artist
             else:
                 library_artist_match_to_input_artist = fuzz.ratio(norm_input_artist_match_str, entry["norm_artist_stripped"])
                 artist_bonus = (library_artist_match_to_input_artist / 100.0) * 1.5 # Slightly reduced bonus scaling
             adjusted_score += artist_bonus
             adjusted_score = min(adjusted_score, 100.0) # Cap score

             original_score_before_penalty = adjusted_score
             penalty_applied = False

             # Apply Live Penalty if applicable
             if not is_input_explicitly_live_format and entry["entry_is_live"]:
                 adjusted_score *= live_penalty_factor
                 penalty_applied = True
                 logging.debug(f"      Applied Penalty (Studio Input, Live Entry): {original_score_before_penalty:.1f} * {live_penalty_factor} -> {adjusted_score:.1f}")

             # Store temporary scores directly in the dictionary for sorting/display later
             entry['_current_score_before_prompt'] = adjusted_score
             entry['_original_score'] = original_score_before_penalty
             entry['_penalty_applied'] = penalty_applied

             # Add to candidates list if final score meets threshold
             if adjusted_score >= match_threshold:
                 scored_candidates.append(entry) # Add the whole entry dictionary
                 logging.debug(f"    QUALIFIED CANDIDATE (Final Score: {adjusted_score:.1f}, Orig: {original_score_before_penalty:.1f}, Penalty: {penalty_applied}, Path: {entry['path']})")
             else:
                 all_title_misses.append((adjusted_score, entry)) # Track misses below threshold for logging
                 logging.debug(f"    Candidate Below Threshold After Penalty/Bonus (Score: {adjusted_score:.1f}, Path: {entry['path']})")
        else:
             # Track entries that didn't even meet the initial base score check
             all_title_misses.append((current_base_score, entry))
             logging.debug(f"    Candidate Base Score Too Low (Base Score: {current_base_score:.1f}, Path: {entry['path']})")

    # --- Decide Action based on Mode and Candidates ---

    # Sort qualified candidates by their final adjusted score (descending)
    scored_candidates.sort(key=lambda x: x.get('_current_score_before_prompt', -1), reverse=True)

    if not scored_candidates:
        # No candidates met the final threshold
        log_msg = f"NO MATCH: No tracks found for '{input_artist} - {input_track}' meeting threshold {match_threshold} after scoring."
        # Log the best overall miss if available
        if all_title_misses:
            all_title_misses.sort(key=lambda x: x[0], reverse=True) # Sort misses by score
            best_miss_score, best_miss_entry = all_title_misses[0]
            log_msg += (f"\n     -> Closest Miss (below threshold): '{best_miss_entry['artist']} - {best_miss_entry['title']}' (Score: {best_miss_score:.1f}, Path: {best_miss_entry['path']})")
        logging.warning(log_msg)

        # If interactive, prompt the user (offer Skip or Random if possible)
        if INTERACTIVE_MODE:
            print(f"\nNo direct match found for '{input_artist} - {input_track}'.")
            # Pass candidate_artist_entries for the 'Random' option source
            return prompt_user_for_choice(input_artist, input_track, [], candidate_artist_entries, is_input_explicitly_live_format, match_threshold)
        else:
            return None # Automatic mode: No match found

    # We have at least one candidate >= threshold

    # If NOT interactive OR only one candidate found: Use automatic logic
    if not INTERACTIVE_MODE or len(scored_candidates) == 1:
         logging.debug("Using Automatic/Single Candidate Logic.")
         # Apply standard prioritization (prefer non-live if input non-live, prefer live if input live)
         best_live_candidate = next((c for c in scored_candidates if c['entry_is_live']), None)
         best_non_live_candidate = next((c for c in scored_candidates if not c['entry_is_live']), None)

         best_overall_match = None
         # Default to the absolute top score if no preference applies or only one type exists
         best_overall_match_fallback = scored_candidates[0]

         if is_input_explicitly_live_format:
             if best_live_candidate:
                 best_overall_match = best_live_candidate
                 logging.debug("Auto Choice: Input is Live, Best Live candidate chosen.")
             elif best_non_live_candidate: # Fallback
                 best_overall_match = best_non_live_candidate
                 logging.warning(f"  AUTO/SINGLE: Input Live, only Studio match found/selected: {best_non_live_candidate['path']} (Score: {best_non_live_candidate['_current_score_before_prompt']:.1f})")
             else: # Should not happen if scored_candidates is not empty
                  best_overall_match = best_overall_match_fallback
                  logging.error("Auto Choice Logic Error: Live input, no live/non-live found, using fallback.")
         else: # Input not explicitly live
             if best_non_live_candidate:
                 best_overall_match = best_non_live_candidate
                 logging.debug("Auto Choice: Input is Studio, Best Studio candidate chosen.")
                 # Optional check: if a live one scored *much* higher even *after* penalty?
                 if best_live_candidate and best_live_candidate['_current_score_before_prompt'] > best_non_live_candidate['_current_score_before_prompt'] + 5:
                     logging.warning(f"  AUTO/SINGLE: Studio input, but LIVE match significantly higher post-penalty. OVERRIDING to LIVE: {best_live_candidate['path']} ({best_live_candidate['_current_score_before_prompt']:.1f} vs {best_non_live_candidate['_current_score_before_prompt']:.1f})")
                     best_overall_match = best_live_candidate
             elif best_live_candidate: # Fallback
                 best_overall_match = best_live_candidate
                 logging.warning(f"  AUTO/SINGLE: Input Studio, only Live match found/selected (score includes penalty): {best_live_candidate['path']} (Score: {best_live_candidate['_current_score_before_prompt']:.1f})")
             else: # Should not happen
                  best_overall_match = best_overall_match_fallback
                  logging.error("Auto Choice Logic Error: Studio input, no live/non-live found, using fallback.")

         if best_overall_match:
             final_score = best_overall_match['_current_score_before_prompt']
             logging.info(f"MATCHED (Auto/Single): '{input_artist} - {input_track}' -> '{best_overall_match['path']}' Score: {final_score:.1f}")
             # Clean up temporary keys before returning
             best_overall_match.pop('_current_score_before_prompt', None)
             best_overall_match.pop('_original_score', None)
             best_overall_match.pop('_penalty_applied', None)
             return best_overall_match
         else:
             logging.error("Internal Error: Scored candidates existed but no best match selected in auto/single mode.")
             return None

    else: # Interactive mode AND multiple candidates >= threshold
        logging.info(f"INTERACTIVE: Multiple candidates ({len(scored_candidates)}) found for '{input_artist} - {input_track}'. Prompting user.")
        # Pass the sorted list of qualified candidates to the prompt function
        # Pass the original full artist matches for the Random option source
        chosen_entry = prompt_user_for_choice(
            input_artist=input_artist,
            input_track=input_track,
            candidates=scored_candidates,
            artist_matches=candidate_artist_entries,
            input_live_format=is_input_explicitly_live_format,
            threshold=match_threshold
        )
        # Clean up temporary keys if an entry was chosen (might be None if skipped)
        if chosen_entry:
            chosen_entry.pop('_current_score_before_prompt', None)
            chosen_entry.pop('_original_score', None)
            chosen_entry.pop('_penalty_applied', None)
        # Return the user's choice (which could be an entry dict or None for skip)
        return chosen_entry


def read_playlist_file(playlist_file_path):
    # (Unchanged)
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
    except FileNotFoundError: logging.error(f"Input playlist file not found: '{playlist_file_path}'"); print(f"Error: Input playlist file '{playlist_file_path}' not found.", file=sys.stderr); sys.exit(1)
    except Exception as e: logging.error(f"Error reading playlist file '{playlist_file_path}': {e}", exc_info=True); print(f"Error reading input file: {e}", file=sys.stderr); sys.exit(1)
    return tracks

def generate_playlist(tracks, input_playlist_path, output_dir_str, mpd_playlist_dir_str, mpd_music_dir_str, match_threshold, log_file_path_obj, missing_tracks_dir_path, live_penalty_factor):
    global library_index
    global INTERACTIVE_MODE # Access global flag if needed here, though primary use is in find_track
    if not library_index:
        logging.error("Library index is empty. Cannot generate playlist.")
        print("Error: Music library index is empty. Please scan first or check library path.", file=sys.stderr)
        return # Exit the function cleanly

    try:
        resolved_mpd_music_dir = Path(mpd_music_dir_str).expanduser().resolve(strict=True)
        logging.info(f"Using MPD music directory for relative paths: {resolved_mpd_music_dir}")
    except FileNotFoundError:
        logging.error(f"MPD music directory does not exist: '{mpd_music_dir_str}'. This must match mpd.conf.")
        print(f"Error: MPD music directory '{mpd_music_dir_str}' not found. Check '--mpd-music-dir' argument.", file=sys.stderr)
        sys.exit(1) # Critical error
    except Exception as e:
        logging.error(f"Error resolving MPD music directory '{mpd_music_dir_str}': {e}")
        print(f"Error resolving MPD music directory: {e}", file=sys.stderr)
        sys.exit(1) # Critical error

    m3u_lines = ["#EXTM3U"]
    skipped_track_inputs = [] # Store original 'Artist - Track' string of skipped/missing tracks
    found_count = 0
    total_tracks = len(tracks)

    print(f"Processing {total_tracks} track entries from input file...")
    for index, (artist, track) in enumerate(tracks):
        print(f"\n[{index + 1}/{total_tracks}] Searching for: {artist} - {track}")
        # find_track_in_index now uses the global INTERACTIVE_MODE implicitly
        matched_entry = find_track_in_index(artist, track, match_threshold, live_penalty_factor)

        if matched_entry:
            # Successfully matched (either automatically or via interaction)
            abs_file_path_from_index = Path(matched_entry['path'])
            duration_val = matched_entry.get('duration', -1) # Use .get for safety
            extinf_artist = matched_entry.get('artist', artist) or artist # Fallback to input artist if metadata empty
            extinf_title = matched_entry.get('title', track) or track # Fallback to input track

            try:
                relative_path = abs_file_path_from_index.relative_to(resolved_mpd_music_dir)
                m3u_path_string = relative_path.as_posix()

                logging.debug(f"M3U Prep: Input='{artist} - {track}'")
                logging.debug(f"  -> Matched: '{extinf_artist} - {extinf_title}'")
                logging.debug(f"  -> Path (abs): {abs_file_path_from_index}")
                logging.debug(f"  -> Path (rel): {m3u_path_string}")
                logging.debug(f"  -> Duration: {duration_val}")

                m3u_lines.append(f"#EXTINF:{duration_val},{extinf_artist} - {extinf_title}")
                m3u_lines.append(m3u_path_string)
                found_count += 1
                print(f"  -> Found: {m3u_path_string}")

            except ValueError as ve:
                # Path is not within MPD music directory
                reason = f"Path not in MPD library tree ({resolved_mpd_music_dir})"
                logging.warning(f"Skipping track: File '{abs_file_path_from_index}' is not within MPD directory '{resolved_mpd_music_dir}'. Reason: {reason}")
                skipped_track_inputs.append(f"{artist} - {track} (Reason: {reason} - Path: {abs_file_path_from_index})")
                print(f"  -> Skipped: Path not relative to MPD music directory.")
                continue
        else:
            # Track not found OR skipped by user in interactive mode
            # The reason should be logged within find_track_in_index or prompt_user_for_choice
            reason = "No suitable match found"
            if INTERACTIVE_MODE:
                reason = "Skipped by user or no match found interactively"
            skipped_track_inputs.append(f"{artist} - {track} (Reason: {reason} - see log for details)")
            print(f"  -> Skipped: {reason}.")
            # Logging is handled inside find_track_in_index/prompt

    # --- Filename Generation & Writing (Unchanged from previous) ---
    input_path_obj = Path(input_playlist_path)
    base_name_no_ext = input_path_obj.stem
    transformed_name_parts = base_name_no_ext.replace('-', ' ').replace('_', ' ').split()
    capitalized_name = ' '.join(word.capitalize() for word in transformed_name_parts if word)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_filename = f"{capitalized_name}_{date_str}.m3u"

    output_dir = Path(output_dir_str).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_m3u_path = output_dir / output_filename
    try:
        with open(output_m3u_path, "w", encoding="utf-8") as f:
            f.write("\n".join(m3u_lines) + "\n")
        print(f"\nGenerated playlist ({found_count}/{total_tracks} tracks included): {output_m3u_path}")
        logging.info(f"Generated playlist '{output_m3u_path}' with {found_count} of {total_tracks} input tracks.")
    except Exception as e:
        logging.error(f"Failed to write playlist to {output_m3u_path}: {e}", exc_info=True)
        print(f"Error writing output playlist {output_m3u_path}: {e}", file=sys.stderr)
        # Decide if we should stop entirely or just skip MPD copy / missing list
        return # Let's stop if the primary output fails

    # --- Optionally copy to MPD playlist directory (Unchanged) ---
    if mpd_playlist_dir_str:
        try:
            mpd_playlist_dir = Path(mpd_playlist_dir_str).expanduser().resolve()
            if not mpd_playlist_dir.is_dir():
                if not mpd_playlist_dir.exists():
                    logging.info(f"MPD playlist directory '{mpd_playlist_dir}' does not exist. Creating.")
                    mpd_playlist_dir.mkdir(parents=True, exist_ok=True)
                else:
                    logging.error(f"MPD playlist path '{mpd_playlist_dir}' exists but is not a directory. Cannot copy playlist.")
                    raise FileNotFoundError(f"Not a directory: {mpd_playlist_dir}")

            mpd_m3u_path = mpd_playlist_dir / output_filename
            with open(mpd_m3u_path, "w", encoding="utf-8") as f:
                f.write("\n".join(m3u_lines) + "\n")
            print(f"Copied playlist to MPD directory: {mpd_m3u_path}")
            logging.info(f"Copied playlist to MPD directory: {mpd_m3u_path}")
        except (FileNotFoundError, PermissionError, Exception) as e:
            logging.error(f"Failed to copy playlist to MPD directory '{mpd_playlist_dir_str}': {e}", exc_info=True)
            print(f"Warning: Failed to copy playlist to MPD directory: {e}", file=sys.stderr)

    # --- Write Missing Tracks File (Unchanged, relies on populated skipped_track_inputs) ---
    if skipped_track_inputs:
        try:
            missing_tracks_dir_path.mkdir(parents=True, exist_ok=True)
            missing_filename_base = f"{capitalized_name}_{date_str}"
            missing_filename = f"{missing_filename_base}-missing-tracks.txt"
            missing_file_path = missing_tracks_dir_path / missing_filename
            with open(missing_file_path, "w", encoding="utf-8") as f_missing:
                f_missing.write(f"# Input playlist: {input_playlist_path}\n")
                f_missing.write(f"# Generated M3U: {output_m3u_path}\n")
                f_missing.write(f"# Date Generated: {datetime.now().isoformat()}\n")
                f_missing.write(f"# {len(skipped_track_inputs)} tracks from input file not found in library or skipped:\n")
                f_missing.write("-" * 30 + "\n")
                for missing_track_info in skipped_track_inputs:
                    f_missing.write(f"{missing_track_info}\n")
            print(f"List of {len(skipped_track_inputs)} missing/skipped tracks saved to: {missing_file_path}")
            logging.info(f"List of {len(skipped_track_inputs)} missing/skipped tracks saved to: {missing_file_path}")
        except Exception as e:
            logging.error(f"Failed to write missing tracks file to {missing_tracks_dir_path}: {e}", exc_info=True)
            print(f"Warning: Failed to write missing tracks file: {e}", file=sys.stderr)

    # --- Log Summary (Unchanged) ---
    if skipped_track_inputs:
        mf_name_for_log = missing_filename if 'missing_filename' in locals() else 'the missing-tracks file'
        logging.warning(f"--- Summary: Skipped {len(skipped_track_inputs)} tracks. See details in '{mf_name_for_log}' and debug logs. ---")
        print(f"Warning: Skipped {len(skipped_track_inputs)} out of {total_tracks} input tracks. See log/missing file.")
    else:
        logging.info("--- Summary: All tracks from input file were matched and included successfully. ---")
        print("All tracks included successfully.")


def main():
    global INTERACTIVE_MODE # To set the global flag
    global PARENTHETICAL_STRIP_REGEX # To compile the regex

    parser = argparse.ArgumentParser(
        description="Generate M3U playlists by matching 'Artist - Track' lines against a music library.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("playlist_file", help="Input text file (one 'Artist - Track' per line).")
    parser.add_argument("-l", "--library", default=DEFAULT_SCAN_LIBRARY, help="Music library path to scan.")
    parser.add_argument("--mpd-music-dir", default=DEFAULT_MPD_MUSIC_DIR_CONF,
                        help="MPD 'music_directory' path (for relative paths in M3U). Must match mpd.conf.")
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory for generated M3U playlists.")
    parser.add_argument("--missing-dir", default=DEFAULT_MISSING_TRACKS_DIR,
                        help="Directory to save lists of tracks that were not found or skipped.")
    parser.add_argument("-m", "--mpd-playlist-dir", default=None, nargs='?', const=DEFAULT_MPD_PLAYLIST_DIR_CONF,
                        help="Optionally copy the generated M3U to MPD's 'playlist_directory'. If flag is present "
                             "without a value, uses the default path. Provide a path to override the default.")
    parser.add_argument("-t", "--threshold", type=int, default=DEFAULT_MATCH_THRESHOLD, choices=range(0, 101), metavar="[0-100]",
                        help="Minimum fuzzy match score [0-100] required for title/filename match.")
    parser.add_argument("--live-penalty", type=float, default=DEFAULT_LIVE_PENALTY_FACTOR, metavar="[0.0-1.0]",
                        help="Score multiplier (penalty) for library tracks marked as 'live' when the input track is not. "
                             "Lower value = higher penalty (e.g., 0.75 means score * 0.75).")
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, type=Path, help="Path for the log file.")
    parser.add_argument("--log-mode", choices=['append', 'overwrite'], default='overwrite', help="Log file mode ('append' or 'overwrite').")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO',
                        help="Set the logging level for the file log.")
    parser.add_argument("-e", "--extensions", nargs='+', default=DEFAULT_SUPPORTED_EXTENSIONS,
                        help="Space-separated list of supported audio file extensions (e.g., .mp3 .flac).")
    parser.add_argument("--live-album-keywords", nargs='+', default=DEFAULT_LIVE_ALBUM_KEYWORDS,
                        help="Space-separated list of regex patterns (case-insensitive) to identify live albums by title.")
    parser.add_argument("--strip-keywords", nargs='+', default=DEFAULT_PARENTHETICAL_STRIP_KEYWORDS,
                        help="Space-separated list of keywords (case-insensitive, treated as regex word boundaries) "
                             "to strip from within parentheses during normalization (e.g., remix edit version).")
    # <<< NEW: INTERACTIVE FLAG >>>
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Enable interactive mode to resolve ambiguous matches, handle missing tracks, "
                             "or confirm substitutions (like live/studio).")

    args = parser.parse_args()

    # Set the global interactive flag
    INTERACTIVE_MODE = args.interactive

    # Validation
    if not (0.0 <= args.live_penalty <= 1.0):
        parser.error("--live-penalty must be between 0.0 and 1.0.")
    supported_extensions = tuple(ext.lower() if ext.startswith('.') else '.' + ext.lower() for ext in args.extensions)

    # Resolve log file path carefully
    log_file_path_resolved = args.log_file
    try:
        # Try resolving relative to script dir first if default name, else resolve normally
        if not args.log_file.is_absolute():
            if args.log_file.name == DEFAULT_LOG_FILE.name :
                 log_file_path_resolved = (SCRIPT_DIR / args.log_file.name).resolve()
            else: # User specified a relative path, resolve from CWD
                 log_file_path_resolved = Path.cwd() / args.log_file.resolve()
        else: # Is absolute
            log_file_path_resolved = args.log_file.resolve()
    except Exception as e:
         print(f"Warning: Could not fully resolve log path {args.log_file}, using as is. Error: {e}", file=sys.stderr)
         # Proceed with the potentially unresolved path, setup_logging will try to handle it

    setup_logging(log_file_path_resolved, args.log_mode)
    # Set file log level based on argument
    log_level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    logging.getLogger().setLevel(log_level_map.get(args.log_level.upper(), logging.INFO))

    logging.info("="*30 + " Playlist Maker Started " + "="*30)
    logging.info(f"Version: 1.4 (Interactive Mode & Enhanced Normalization)")
    logging.info(f"Interactive Mode Enabled: {INTERACTIVE_MODE}")
    logging.info(f"Input File: {args.playlist_file}")
    logging.info(f"Library Scan Path: {args.library}")
    logging.info(f"MPD Music Dir: {args.mpd_music_dir}")
    logging.info(f"Output Dir: {args.output_dir}")
    logging.info(f"Missing Tracks Dir: {args.missing_dir}")
    logging.info(f"MPD Playlist Copy Dir: {args.mpd_playlist_dir if args.mpd_playlist_dir is not None else 'Not specified'}")
    logging.info(f"Match Threshold: {args.threshold}")
    logging.info(f"Live Penalty Factor: {args.live_penalty}")
    logging.info(f"Log File: {log_file_path_resolved} (Mode: {args.log_mode}, Level: {args.log_level})")
    logging.info(f"Supported Extensions: {supported_extensions}")

    # Compile regex patterns
    try:
        live_album_regex_pattern = r"(" + "|".join(args.live_album_keywords) + r")"
        live_album_keywords_regex = re.compile(live_album_regex_pattern, re.IGNORECASE)
        logging.info(f"Using live album detection regex: {live_album_regex_pattern}")

        # Compile regex for stripping keywords from parentheses
        strip_keywords_pattern = r"\b(?:" + "|".join(re.escape(kw) for kw in args.strip_keywords) + r")\b"
        # Allow optional surrounding non-alphanumeric characters for robustness
        strip_keywords_full_pattern = r"^\s*(?:" + strip_keywords_pattern + r")\s*(?:[\W_].*)?$"
        PARENTHETICAL_STRIP_REGEX = re.compile(strip_keywords_full_pattern, re.IGNORECASE)
        logging.info(f"Using parenthetical strip keyword regex: {strip_keywords_full_pattern}")

    except re.error as e:
        logging.error(f"Invalid regex pattern in --live-album-keywords or --strip-keywords: {e}")
        print(f"Error: Invalid regex pattern provided: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve other essential paths early
    missing_tracks_dir_resolved = Path(args.missing_dir).expanduser().resolve()
    try:
        # Resolve and check existence for critical paths
        playlist_file_abs = Path(args.playlist_file).resolve(strict=True)
        library_abs = Path(args.library).expanduser().resolve(strict=True)
        mpd_music_dir_abs = Path(args.mpd_music_dir).expanduser().resolve(strict=True) # Checked again later, but good for early fail
        output_dir_abs = Path(args.output_dir).expanduser().resolve() # Don't need strict=True here, will be created
        # Log resolved paths
        logging.info(f"Resolved Input Playlist: {playlist_file_abs}")
        logging.info(f"Resolved Library Scan Path: {library_abs}")
        logging.info(f"Resolved MPD Music Dir: {mpd_music_dir_abs}")
        logging.info(f"Resolved Output Dir: {output_dir_abs}")
        logging.info(f"Resolved Missing Tracks Dir: {missing_tracks_dir_resolved}")
    except FileNotFoundError as e:
        logging.error(f"Essential path does not exist: {e}. Please check arguments. Exiting.")
        print(f"Error: Essential path not found: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error resolving essential paths: {e}", exc_info=True)
        print(f"Error resolving paths: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Main Execution Flow ---
    tracks = read_playlist_file(args.playlist_file)
    if not tracks:
        logging.error("Exiting: No valid track entries read from the input file.")
        print(f"Error: No valid 'Artist - Track' lines found in '{args.playlist_file}'.", file=sys.stderr)
        sys.exit(1)
    print(f"Read {len(tracks)} track entries from '{args.playlist_file}'.")

    # Pass compiled regex to scan_library
    scan_library(args.library, supported_extensions, live_album_keywords_regex)
    if not library_index:
        logging.error("Exiting: Library scan found no supported audio tracks.")
        print("Error: Library scan did not find any tracks. Check the library path and supported extensions.", file=sys.stderr)
        sys.exit(1)

    # generate_playlist now implicitly uses INTERACTIVE_MODE flag set earlier
    generate_playlist(
        tracks=tracks,
        input_playlist_path=args.playlist_file,
        output_dir_str=args.output_dir,
        mpd_playlist_dir_str=args.mpd_playlist_dir, # Pass the value from args (could be None)
        mpd_music_dir_str=args.mpd_music_dir,
        match_threshold=args.threshold,
        log_file_path_obj=log_file_path_resolved,
        missing_tracks_dir_path=missing_tracks_dir_resolved,
        live_penalty_factor=args.live_penalty
    )

    logging.info("Playlist Maker script finished successfully.")
    print("\nDone.")

if __name__ == "__main__":
    # Check for pandas, create dummy if not found (for pd.isna)
    try:
        import pandas as pd
        logging.debug("Pandas library found and imported.")
    except ImportError:
        class DummyPandas:
            def isna(self, val):
                # Basic check for None or float NaN
                if val is None: return True
                try: return val != val # NaN comparison trick
                except TypeError: return False # Not comparable, not NaN
        pd = DummyPandas()
        logging.info("Pandas library not found; using basic duration checks (None/NaN).")
        print("INFO: Pandas not found; using basic duration checks.") # Also print to console

    main()