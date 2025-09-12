# playlist_maker/app.py

import os
import sys
import logging
from pathlib import Path
import re # For regex compilation in main
from datetime import datetime # For filename generation

# --- Bootstrap Logging (runs when module is imported) ---
# This ensures that any errors during the import process of app.py or its
# dependencies have a chance to be logged *before* main() gets to its robust setup_logging.
try:
    # For bootstrap, log to a known, writable location.
    # Using a user cache directory is often a good choice.
    bootstrap_log_dir = Path.home() / ".cache" / "playlist-maker" / "logs"
    bootstrap_log_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_log_file = bootstrap_log_dir / "app_bootstrap.log"
    
    # BasicConfig for bootstrap:
    # - `force=True` allows main's setup_logging to reconfigure without issue.
    # - `filemode='a'` to append bootstrap errors over time.
    logging.basicConfig(
        level=logging.DEBUG, # Capture all details for bootstrap issues
        format="%(asctime)s - BOOTSTRAP - %(levelname)s - [%(name)s:%(funcName)s:%(lineno)d] - %(message)s",
        filename=str(bootstrap_log_file),
        filemode='a',
        force=True
    )
    logging.info(f"Bootstrap logging for '{__name__}' module initialized. Log file: {bootstrap_log_file}")
except Exception as e:
    # If bootstrap logging itself fails, print to stderr as a last resort.
    print(f"CRITICAL BOOTSTRAP LOGGING FAILED: {e}. Further log messages may be lost until main setup.", file=sys.stderr)
# --- End Bootstrap Logging ---


# --- Project-specific Imports ---
# Core
from .core import constants # Note the relative import '.'
from .core.library_service import LibraryService
from .core.matching_service import MatchingService, InteractionRequired
from .core.playlist_service import PlaylistService

# UI
from .ui.cli_interface import Colors, Symbols, colorize
from .ui.argument_parser import parse_arguments
from .ui.interactive_prompts import prompt_user_for_choice, prompt_album_selection_or_skip

# Utils
from .utils.logging_setup import setup_logging
from .utils.file_utils import format_output_filename
from .utils.normalization_utils import normalize_and_detect_specific_live_format, check_album_for_live_indicators # If still needed directly by main
# config.manager is used via get_config_value, which is fine.
from .config.manager import load_config_files, get_config_value

from .core.ai_service import AIService

# --- Global Application State (scoped to this module if possible, or passed around) ---
# These are set by main() and used by functions it calls (or passed as params)
INTERACTIVE_MODE: bool = False
PARENTHETICAL_STRIP_REGEX = None # Compiled regex object

def validate_api_key(api_key: str | None) -> bool:
    """Validate OpenAI API key format."""
    if not api_key:
        return False
    # Basic validation: OpenAI keys typically start with 'sk-' and are 51 characters
    return api_key.startswith('sk-') and len(api_key) >= 20

def validate_file_path(file_path: str | Path) -> tuple[bool, str]:
    """Validate that a file path exists and is accessible."""
    try:
        path_obj = Path(file_path).resolve(strict=True)
        if path_obj.is_file():
            return True, ""
        else:
            return False, f"Path exists but is not a file: {path_obj}"
    except FileNotFoundError:
        return False, f"File not found: {file_path}"
    except PermissionError:
        return False, f"Permission denied: {file_path}"
    except Exception as e:
        return False, f"Invalid path: {e}"


def main(argv_list=None) -> dict: # main now explicitly returns a dict for status
    """
    Main application orchestration logic.
    
    Parses arguments, loads config, initializes services, processes playlist, and writes output.
    Handles both AI-generated playlists and text file input, with comprehensive error handling.
    
    Args:
        argv_list: Optional list of command-line arguments (defaults to sys.argv)
        
    Returns:
        dict: Status dictionary with keys:
            - success: bool - Whether the operation succeeded
            - error: str - Error message if success is False
            - skipped_tracks: list - List of tracks that couldn't be matched
            - message: str - Optional informational message
    """
    global INTERACTIVE_MODE, PARENTHETICAL_STRIP_REGEX # Allow main to modify these module-level globals
    library_service = None # Initialize for finally block

    # --- 1. Initial Setup: Project Root, Config, Args ---
    project_root_dir = Path.cwd()
    
    try:
        # If app.py is in playlist_maker/, __file__.parent.parent is project_root
        project_root_dir = Path(__file__).resolve().parent.parent
    except NameError: # __file__ not defined (e.g., interactive testing, though unlikely for app entry)
        logging.warning("Could not determine project root from __file__, using CWD.")
        pass # Keep CWD
    
    # Load configurations (from config.manager)
    # load_config_files now takes project_root_dir to find local .conf
    loaded_config_files = load_config_files(project_root_dir)
    
    # Parse command-line arguments (from ui.argument_parser)
    args = parse_arguments(argv_list)

    # --- 2. Determine Final Configuration Values ---
    # This extensive block uses get_config_value and args to resolve all settings
    # (Copied from your previous main, using constants.DEFAULT_... for fallbacks)
    final_library_path = args.library if args.library is not None else get_config_value("Paths", "library", constants.DEFAULT_SCAN_LIBRARY)
    final_mpd_music_dir = args.mpd_music_dir if args.mpd_music_dir is not None else get_config_value("Paths", "mpd_music_dir", constants.DEFAULT_MPD_MUSIC_DIR_CONF)
    final_output_dir_str = args.output_dir if args.output_dir is not None else get_config_value("Paths", "output_dir", constants.DEFAULT_OUTPUT_DIR)
    final_missing_dir_str = args.missing_dir if args.missing_dir is not None else get_config_value("Paths", "missing_dir", constants.DEFAULT_MISSING_TRACKS_DIR)
    
    final_mpd_playlist_dir_str = None
    if args.mpd_playlist_dir is not None:
        if args.mpd_playlist_dir == "USE_DEFAULT_OR_CONFIG":
             config_val = get_config_value("Paths", "mpd_playlist_dir", fallback="USE_DEFAULT_CONST")
             if config_val == "USE_DEFAULT_CONST": final_mpd_playlist_dir_str = constants.DEFAULT_MPD_PLAYLIST_DIR_CONF
             elif config_val: final_mpd_playlist_dir_str = config_val
             else: final_mpd_playlist_dir_str = None
        else: final_mpd_playlist_dir_str = args.mpd_playlist_dir
    else:
        config_val = get_config_value("Paths", "mpd_playlist_dir", fallback=None)
        final_mpd_playlist_dir_str = config_val if config_val else None

    final_threshold = args.threshold if args.threshold is not None else get_config_value("Matching", "threshold", constants.DEFAULT_MATCH_THRESHOLD, int)
    final_live_penalty = args.live_penalty if args.live_penalty is not None else get_config_value("Matching", "live_penalty", constants.DEFAULT_LIVE_PENALTY_FACTOR, float)
    final_live_album_kws = args.live_album_keywords if args.live_album_keywords is not None else get_config_value("Matching", "live_album_keywords", constants.DEFAULT_LIVE_ALBUM_KEYWORDS, list)
    final_strip_keywords = args.strip_keywords if args.strip_keywords is not None else get_config_value("Matching", "strip_keywords", constants.DEFAULT_PARENTHETICAL_STRIP_KEYWORDS, list)
    
    final_output_name_format_str = args.output_name_format
    if final_output_name_format_str is None:
        final_output_name_format_str = get_config_value("General", "output_name_format", constants.DEFAULT_OUTPUT_NAME_FORMAT, str)

    # Log File Path determination (project_root_dir is defined above)
    default_log_path = project_root_dir / constants.DEFAULT_LOG_FILE_NAME
    config_log_file_str = get_config_value("Logging", "log_file", str(default_log_path))
    final_log_file_path_obj = args.log_file if args.log_file is not None else Path(config_log_file_str)

    final_log_mode = args.log_mode if args.log_mode is not None else get_config_value("Logging", "log_mode", "overwrite")
    final_log_level_str = args.log_level if args.log_level is not None else get_config_value("Logging", "log_level", "INFO")
    final_extensions = args.extensions if args.extensions is not None else get_config_value("General", "extensions", constants.DEFAULT_SUPPORTED_EXTENSIONS, list)

    # Set global INTERACTIVE_MODE (used by prompt functions if they are not passed this state)
    if args.interactive is True: INTERACTIVE_MODE = True
    elif args.interactive is None: INTERACTIVE_MODE = get_config_value("General", "interactive", fallback=False, expected_type=bool)
    else: INTERACTIVE_MODE = False
    logging.info(f"Interactive mode: {INTERACTIVE_MODE}")

    final_enable_library_cache = get_config_value("Cache", "enable_library_cache", constants.DEFAULT_ENABLE_LIBRARY_CACHE, bool)
    final_library_index_db_filename = get_config_value("Cache", "index_db_filename", constants.DEFAULT_LIBRARY_INDEX_DB_FILENAME, str)
    # Construct full DB path relative to project root's 'data' subdirectory
    library_index_db_full_path = project_root_dir / "data" / final_library_index_db_filename

    # --- Get AI Config Values ---
    # Order: CLI arg -> Environment Var -> Config file -> Python Constant Default
    # AIService handles env var internally if config/arg is None.
    final_ai_api_key_from_config = get_config_value("AI", "api_key", fallback=None, expected_type=str)
    # No direct CLI arg for api_key in this example, but could be added to args.
    # AIService will use final_ai_api_key_from_config, and if that's None, it will check os.environ.
    
    final_ai_model_from_cli = args.ai_model # This can be None
    final_ai_model_from_config = get_config_value("AI", "model", fallback=None, expected_type=str)
    # Determine effective AI model: CLI > Config > Python Default (constants.DEFAULT_AI_MODEL)
    effective_ai_model = final_ai_model_from_cli if final_ai_model_from_cli else \
                         final_ai_model_from_config if final_ai_model_from_config else \
                         constants.DEFAULT_AI_MODEL
    logging.info(f"Effective AI model for generation: {effective_ai_model if args.ai_prompt else 'Not used'}")

    # --- Get "Save AI Suggestions" Config ---
    final_save_ai_suggestions = get_config_value("AI", "save_ai_suggestions", 
                                                 constants.DEFAULT_SAVE_AI_SUGGESTIONS, bool)
    final_ai_suggestions_dir_str = get_config_value("AI", "ai_suggestions_log_dir", 
                                                    constants.DEFAULT_AI_SUGGESTIONS_LOG_DIR, str)
    
    # Expand and resolve AI suggestions directory path
    # Done after project_root_dir is established
    ai_suggestions_abs_dir_path = project_root_dir / Path(os.path.expanduser(final_ai_suggestions_dir_str))

    # --- 3. Path Expansion and Validation ---
    final_library_path = os.path.expanduser(final_library_path)
    final_output_dir_str = os.path.expanduser(final_output_dir_str)
    final_missing_dir_str = os.path.expanduser(final_missing_dir_str)
    if final_mpd_playlist_dir_str: final_mpd_playlist_dir_str = os.path.expanduser(final_mpd_playlist_dir_str)
    
    try: # Resolve log path *after* expansion
        final_log_file_path_obj = Path(os.path.expanduser(str(final_log_file_path_obj))).resolve()
    except Exception as e: # Broad catch for issues like non-existent parent during resolve
        # Attempt to use the unverified path but log a clear warning.
        # setup_logging itself has fallbacks if directory creation fails.
        unverified_log_path = Path(os.path.expanduser(str(final_log_file_path_obj)))
        logging.warning(f"Could not fully resolve log path '{final_log_file_path_obj}': {e}. Attempting to use unverified path: {unverified_log_path}", exc_info=True)
        final_log_file_path_obj = unverified_log_path


    # Post-processing / Validation of config values
    if not (constants.DEFAULT_THRESHOLD_MIN <= final_threshold <= constants.DEFAULT_THRESHOLD_MAX):
        logging.error(f"Invalid threshold: {final_threshold}. Must be 0-100.")
        print(colorize(f"Error: --threshold ({final_threshold}) must be between {constants.DEFAULT_THRESHOLD_MIN} and {constants.DEFAULT_THRESHOLD_MAX}.", Colors.RED), file=sys.stderr)
        sys.exit(2) # Argparse typically uses exit code 2 for bad arguments
    if not (0.0 <= final_live_penalty <= 1.0):
        logging.error(f"Invalid live penalty: {final_live_penalty}. Must be 0.0-1.0.")
        print(colorize(f"Error: --live-penalty ({final_live_penalty}) must be between 0.0 and 1.0.", Colors.RED), file=sys.stderr)
        sys.exit(2)
    final_supported_extensions_tuple = tuple(ext.lower() if ext.startswith('.') else '.' + ext.lower() for ext in final_extensions if ext)

    # --- 4. Setup Application Logging ---
    # This call will reconfigure logging, potentially overwriting bootstrap config.
    setup_logging(final_log_file_path_obj, final_log_mode) # From utils.logging_setup
    log_level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}
    final_log_level = log_level_map.get(final_log_level_str.upper(), logging.INFO)
    logging.getLogger().setLevel(final_log_level) # Set the root logger's level for file output

    # Log effective settings
    logging.info(f"--- Playlist Maker {constants.VERSION} Initializing ---")
    logging.info(f"Command: {' '.join(sys.argv)}")
    logging.info(f"Loaded config files: {', '.join(map(str, loaded_config_files)) if loaded_config_files else 'None'}")
    # Log other key final_... values if desired for debugging.
    logging.info(f"Effective log file: {final_log_file_path_obj}, Mode: {final_log_mode}, Level: {final_log_level_str}")
    logging.info(f"Effective output name format: {final_output_name_format_str}")


    # --- 5. Compile Regex Patterns ---
    # Compile live album keywords regex
    live_album_keywords_regex_obj = None
    if final_live_album_kws:
        try:
            live_album_regex_pattern = r"(" + "|".join(final_live_album_kws) + r")"
            live_album_keywords_regex_obj = re.compile(live_album_regex_pattern, re.IGNORECASE)
            logging.info(f"Using live album regex: {live_album_regex_pattern}")
        except re.error as e:
            logging.error(f"Invalid regex pattern for live album keywords: {e}", exc_info=True)
            print(colorize(f"Error: Invalid live album regex: {e}", Colors.RED), file=sys.stderr)
            return {"success": False, "error": f"Invalid live album regex: {e}", "skipped_tracks": []}
    
    # Compile parenthetical strip regex (sets module-level global PARENTHETICAL_STRIP_REGEX)
    if final_strip_keywords:
        try:
            strip_keywords_pattern = r"|".join(r"(?:\W|^)" + re.escape(kw) + r"(?:\W|$)" for kw in final_strip_keywords)
            PARENTHETICAL_STRIP_REGEX = re.compile(strip_keywords_pattern, re.IGNORECASE)
            logging.info(f"Using parenthetical strip regex: {strip_keywords_pattern}")
        except re.error as e:
            logging.error(f"Invalid regex pattern for strip keywords: {e}", exc_info=True)
            print(colorize(f"Error: Invalid strip keyword regex: {e}", Colors.RED), file=sys.stderr)
            return {"success": False, "error": f"Invalid strip keyword regex: {e}", "skipped_tracks": []}

    # --- 6. Resolve Essential File Paths (Absolute) ---
    input_playlist_file_abs_path = None # Initialize
    if args.playlist_file: # Only resolve if a file path was actually given
        # Validate the playlist file path
        is_valid, error_msg = validate_file_path(args.playlist_file)
        if not is_valid:
            logging.error(f"Input playlist file validation failed: {error_msg}", exc_info=True)
            print(colorize(f"Error: {error_msg}", Colors.RED), file=sys.stderr)
            print(colorize("  • Check that the file path is correct and the file exists", Colors.YELLOW), file=sys.stderr)
            print(colorize("  • Ensure the file contains 'Artist - Track' entries (one per line)", Colors.YELLOW), file=sys.stderr)
            print(colorize("  • Use absolute paths or ensure relative paths are correct", Colors.YELLOW), file=sys.stderr)
            return {"success": False, "error": f"Input playlist file validation failed: {error_msg}"}
        
        try:
            input_playlist_file_abs_path = Path(args.playlist_file).resolve(strict=True)
            logging.info(f"Resolved input playlist file: {input_playlist_file_abs_path}")
        except FileNotFoundError as e:
            # This error specific to playlist_file, if it was the chosen input method
            logging.error(f"Input playlist file '{args.playlist_file}' not found: {e}", exc_info=True)
            print(colorize(f"Error: Input playlist file '{args.playlist_file}' not found.", Colors.RED), file=sys.stderr)
            print(colorize("  • Check that the file path is correct and the file exists", Colors.YELLOW), file=sys.stderr)
            print(colorize("  • Ensure the file contains 'Artist - Track' entries (one per line)", Colors.YELLOW), file=sys.stderr)
            print(colorize("  • Use absolute paths or ensure relative paths are correct", Colors.YELLOW), file=sys.stderr)
            return {"success": False, "error": f"Input playlist file not found: {args.playlist_file}"}
    # Other essential paths
    try:
        library_abs_path = Path(final_library_path).resolve(strict=True)
        output_dir_abs_path = Path(final_output_dir_str).resolve()
        missing_tracks_dir_abs_path = Path(final_missing_dir_str).resolve()
    except FileNotFoundError as e: # For library, mpd_music_dir
        logging.error(f"Essential path does not exist: {e}.", exc_info=True)
        print(colorize(f"Error: Essential directory not found: {e}", Colors.RED), file=sys.stderr)
        print(colorize("  • Check that your music library path exists and is accessible", Colors.YELLOW), file=sys.stderr)
        print(colorize("  • Verify the path in your config file or command line arguments", Colors.YELLOW), file=sys.stderr)
        print(colorize("  • Use absolute paths or ensure relative paths are correct", Colors.YELLOW), file=sys.stderr)
        return {"success": False, "error": f"Essential directory not found: {e}"}

    # --- 7. Determine Output M3U Filename ---
    # Uses format_output_filename from utils.file_utils
    raw_playlist_basename = args.ai_prompt if args.ai_prompt else \
                            input_playlist_file_abs_path.stem if input_playlist_file_abs_path else \
                            "ai_playlist" # Fallback basename if AI prompt is empty or file is somehow None
    if args.ai_prompt: # Sanitize AI prompt for use as basename
        raw_playlist_basename = re.sub(r'\W+', '_', args.ai_prompt.lower().strip())[:constants.DEFAULT_AI_PROMPT_MAX_LENGTH]
        if not raw_playlist_basename: raw_playlist_basename = "ai_generated_playlist"

    current_time = datetime.now()
    generated_m3u_filename_stem_ext = format_output_filename(
        final_output_name_format_str, raw_playlist_basename, current_time
    )
    full_output_m3u_filepath = output_dir_abs_path / generated_m3u_filename_stem_ext
    logging.info(f"Target M3U output filepath: {full_output_m3u_filepath} (basename source: '{raw_playlist_basename}')")

    # --- 8. Initialize Services ---
    matching_service = MatchingService(INTERACTIVE_MODE) # Pass interactive status
    playlist_service = PlaylistService()
    ai_service = AIService(api_key=final_ai_api_key_from_config, default_model=constants.DEFAULT_AI_MODEL)
    try:
        library_service = LibraryService(db_path=library_index_db_full_path)
    except ConnectionError as e: # Catch DB connection error from LibraryService.__init__
        print(colorize(f"Error initializing library cache DB: {e}", Colors.RED), file=sys.stderr)
        logging.critical(f"MAIN: Failed to initialize LibraryService due to DB connection error: {e}", exc_info=True)
        return {"success": False, "error": f"Library cache DB init failed: {e}"}
    
    matching_service = MatchingService(INTERACTIVE_MODE)
    playlist_service = PlaylistService()
    ai_service = None # Initialize
    if args.ai_prompt:
        try:
            ai_service = AIService(api_key=final_ai_api_key_from_config, default_model=constants.DEFAULT_AI_MODEL)
        except ImportError as e:
             print(colorize(f"Error: {e}", Colors.RED), file=sys.stderr)
             if library_service: library_service.close_db() # Close DB if opened
             return {"success": False, "error": str(e)}

    # --- Print User-Facing Header ---
    print(f"{Colors.CYAN}{Colors.BOLD}=== Playlist Maker {constants.VERSION} ==={Colors.RESET}")
    if loaded_config_files: print(f"{Symbols.INFO} Config files loaded: {', '.join(map(str, loaded_config_files))}")
    else: print(f"{Symbols.INFO} No local configuration files loaded (or files were empty/invalid).")
    print(f"{Colors.CYAN}{'-'*45}{Colors.RESET}")

    # Initialize these for use in the main logic block
    input_track_tuples = []
    source_description_for_missing_header = "Unknown Input" # Default
    input_playlist_file_abs_path = None # Will be set if file input is used

    # --- 9. Get Input Tracks (from AI or File) ---
    user_accepted_ai_list_for_processing = False # Flag specific to AI path

    if args.ai_prompt:
        source_description_for_missing_header = f"AI Prompt: {args.ai_prompt[:70]}..." # For missing file header
        print(f"{Symbols.INFO} Generating playlist from AI prompt: \"{args.ai_prompt}\" using model {effective_ai_model}...")
        
        # Validate API key if provided
        if final_ai_api_key_from_config and not validate_api_key(final_ai_api_key_from_config):
            print(colorize("Warning: API key format appears invalid (should start with 'sk-' and be at least 20 characters)", Colors.YELLOW), file=sys.stderr)
        
        if not ai_service or not ai_service.client: # Check if ai_service was initialized and client is ready
            print(colorize("Error: AI Service not available.", Colors.RED), file=sys.stderr)
            print(colorize("  • Check that your OpenAI API key is set in config file or OPENAI_API_KEY environment variable", Colors.YELLOW), file=sys.stderr)
            print(colorize("  • Ensure 'openai' library is installed: pip install openai", Colors.YELLOW), file=sys.stderr)
            print(colorize("  • Verify your API key is valid and has sufficient credits", Colors.YELLOW), file=sys.stderr)
            if library_service: library_service.close_db()
            return {"success": False, "error": "AI Service not available (API key/library issue)."}
        try:
            print(f"{Symbols.INFO} Calling OpenAI API to generate playlist...")
            input_track_tuples = ai_service.generate_playlist_from_prompt(args.ai_prompt, effective_ai_model)
            
            if not input_track_tuples:
                print(colorize("Warning: AI returned an empty or unparsable playlist.", Colors.YELLOW), file=sys.stderr)
            else: # AI returned tracks
                print(f"{Symbols.SUCCESS} AI generated {len(input_track_tuples)} track suggestions.")

                # --- SAVE AI SUGGESTIONS (BEFORE CONFIRMATION FOR LIBRARY PROCESSING) ---
                if final_save_ai_suggestions:
                    try:
                        ai_suggestions_abs_dir_path.mkdir(parents=True, exist_ok=True)
                        sane_prompt_fname = re.sub(r'\W+', '_', args.ai_prompt.lower().strip())[:40]
                        if not sane_prompt_fname: sane_prompt_fname = "ai_playlist"
                        timestamp_fname = datetime.now().strftime("%Y%m%d_%H%M%S")
                        ai_log_filename = f"ai_suggestions_{sane_prompt_fname}_{timestamp_fname}.txt"
                        ai_log_filepath = ai_suggestions_abs_dir_path / ai_log_filename

                        with open(ai_log_filepath, "w", encoding="utf-8") as f_ai_log:
                            f_ai_log.write(f"# AI Prompt: {args.ai_prompt}\n")
                            f_ai_log.write(f"# Model Used: {effective_ai_model}\n")
                            f_ai_log.write(f"# Generated At: {datetime.now().isoformat()}\n")
                            f_ai_log.write("# --- Suggested Tracks ---\n")
                            for art, tit in input_track_tuples: # Corrected variable names
                                f_ai_log.write(f"{art} - {tit}\n")
                        logging.info(f"MAIN: Saved AI-generated track suggestions to: {ai_log_filepath}")
                        print(colorize(f"{Symbols.INFO} Raw AI suggestions saved to: {ai_log_filepath}", Colors.BLUE))
                    except Exception as e_ai_save:
                        logging.error(f"MAIN: Failed to save AI suggestions: {e_ai_save}", exc_info=True)
                        print(colorize(f"{Symbols.WARNING} Could not save AI suggestions list: {e_ai_save}", Colors.YELLOW))
                # --- END SAVE AI SUGGESTIONS ---

                # --- Display AI Playlist and Ask for Confirmation to process against LIBRARY ---
                print(f"\n{Colors.CYAN}{Colors.BOLD}--- AI Generated Playlist Preview ---{Colors.RESET}")
                for i, (art, tit) in enumerate(input_track_tuples): # Corrected variable names
                    print(f"  {i+1:02d}. {colorize(art, Colors.MAGENTA)} - {colorize(tit, Colors.CYAN)}")
                print("-" * 35)
                while True:
                    confirm_choice = input(colorize("Proceed with processing this AI-generated playlist against your library? (yes/no): ", Colors.BLUE + Colors.BOLD)).lower().strip()
                    if confirm_choice in ['yes', 'y']:
                        logging.info("User accepted AI-generated playlist for library processing.")
                        user_accepted_ai_list_for_processing = True
                        break 
                    elif confirm_choice in ['no', 'n']:
                        print(colorize("AI-generated playlist will NOT be processed against library. Suggestions were saved (if enabled).", Colors.YELLOW))
                        logging.info("User rejected processing AI-generated playlist against library.")
                        if library_service: library_service.close_db()
                        return {"success": True, # Program ran, user made a choice
                                "skipped_tracks": [], 
                                "message": "AI playlist suggestions saved; library processing rejected by user."}
                    else:
                        print(colorize("Invalid choice. Please enter 'yes' or 'no'.", Colors.RED))
                # --- END CONFIRMATION FOR LIBRARY PROCESSING ---
            
            # If AI returned tracks but user rejected processing them, clear input_track_tuples
            if input_track_tuples and not user_accepted_ai_list_for_processing:
                 input_track_tuples = [] 

        except ConnectionError as e:
            print(colorize(f"Error generating playlist with AI: {e}", Colors.RED), file=sys.stderr)
            if library_service: library_service.close_db()
            return {"success": False, "error": str(e)}
        except Exception as e:
            print(colorize(f"An unexpected error occurred during AI playlist generation: {e}", Colors.RED), file=sys.stderr)
            logging.error("MAIN: Unexpected error during AI playlist generation.", exc_info=True)
            if library_service: library_service.close_db()
            return {"success": False, "error": f"Unexpected AI error: {e}"}
    
    elif args.playlist_file: # File input mode
        try:
            input_playlist_file_abs_path = Path(args.playlist_file).resolve(strict=True)
            source_description_for_missing_header = str(input_playlist_file_abs_path)
            logging.info(f"MAIN: Using input playlist file: {input_playlist_file_abs_path}")
        except FileNotFoundError:
            logging.error(f"Input playlist file '{args.playlist_file}' not found.")
            print(colorize(f"Error: Input playlist file '{args.playlist_file}' not found.", Colors.RED), file=sys.stderr)
            if library_service: library_service.close_db()
            return {"success": False, "error": f"Input playlist file not found: {args.playlist_file}"}
        
        print(f"Reading input file: {input_playlist_file_abs_path}...")
        try:
            input_track_tuples = playlist_service.read_input_playlist(str(input_playlist_file_abs_path))
        except Exception as e:
            print(colorize(f"Error reading input playlist '{input_playlist_file_abs_path}': {e}", Colors.RED), file=sys.stderr)
            logging.error(f"MAIN: Failed to read input playlist '{input_playlist_file_abs_path}': {e}", exc_info=True)
            if library_service: library_service.close_db()
            return {"success": False, "error": f"Error reading input playlist: {e}"}
    
    if not input_track_tuples:
        print(colorize("No tracks to process. Exiting.", Colors.YELLOW), file=sys.stderr)
        if library_service: library_service.close_db()
        return {"success": True, "skipped_tracks": [], "message": "No tracks available or chosen for processing."}
    
    num_input_tracks = len(input_track_tuples)
    # This message was slightly modified to reflect source_type (AI or File)
    if args.ai_prompt and user_accepted_ai_list_for_processing: # Check user_accepted flag here
        print(f"Proceeding to process {num_input_tracks} AI-generated track entries against library...")
    elif args.playlist_file:
        print(f"Successfully obtained {num_input_tracks} track entries from file for processing.")
    # If AI prompt was used but user rejected processing, input_track_tuples is empty, caught by "No tracks to process"

    # --- 10. Scan Music Library ---
    # library_service.scan_library prints its own progress and summary
    logging.info(f"MAIN: Starting library scan. Force rescan: {args.force_rescan}, Use cache: {final_enable_library_cache}")
    scan_successful = library_service.scan_library(
        str(library_abs_path),
        final_supported_extensions_tuple,
        live_album_keywords_regex_obj,
        PARENTHETICAL_STRIP_REGEX,
        force_rescan=args.force_rescan, # Pass the new CLI argument
        use_cache=final_enable_library_cache # Pass the config setting
    )
    if not scan_successful:
        if library_service: library_service.close_db() # Important: close DB even on scan failure
        return {"success": False, "error": "Library scan failed or found no tracks"}
    current_library_index = library_service.get_library_index()


    # --- 11. Process Tracks & Build M3U Data Structures ---
    m3u_lines_for_file = ["#EXTM3U"] # Initialize M3U content list
    skipped_track_details_for_file = []   # For the -missing-tracks.txt file
    found_tracks_count = 0              # Count of tracks successfully added to M3U

    print(f"\n{colorize('Processing Playlist:', Colors.CYAN)} {colorize(str(len(input_track_tuples)), Colors.BOLD)} input tracks against library of {len(current_library_index)} tracks.")
    print(f"{Colors.CYAN}{'-'*45}{Colors.RESET}")

    for index, (input_artist_str, input_title_str) in enumerate(input_track_tuples):
        original_input_line = f"{input_artist_str} - {input_title_str}" # For logging and missing file
        
        if index > 0: print(f"{Colors.BLUE}{'.' * 20}{Colors.RESET}") # Visual separator
        print(f"{Colors.CYAN}[{index + 1:02d}/{len(input_track_tuples):02d}]{Colors.RESET} {colorize('Input:', Colors.BOLD)} {original_input_line}")

        match_result_obj = matching_service.find_best_track_match(
            input_artist_str, input_title_str,
            final_threshold, final_live_penalty,
            current_library_index, # Pass the scanned library index
            PARENTHETICAL_STRIP_REGEX # Pass compiled regex (module-level global)
        )

        chosen_match_entry_dict = None # Will store the dict of the chosen track, or None
        
        if isinstance(match_result_obj, InteractionRequired):
            interaction_data = match_result_obj # For clarity
            # Call appropriate UI prompt function (from ui.interactive_prompts)
            # These functions return the chosen entry dict or None.
            if interaction_data.reason == "no_artist_match":
                print(colorize(f"\nNo potential artists found containing '{interaction_data.input_artist}'. Offering skip/random.", Colors.YELLOW))
                chosen_match_entry_dict = prompt_user_for_choice(
                    interaction_data.input_artist, interaction_data.input_track,
                    [], [], # No candidates, no specific artist matches for this reason
                    interaction_data.is_input_explicitly_live_format,
                    interaction_data.match_threshold
                )
            elif interaction_data.reason == "no_direct_match_album_selection_possible":
                print(colorize(f"\nNo direct match for '{interaction_data.input_artist} - {interaction_data.input_track}'. Offering album selection.", Colors.YELLOW))
                chosen_match_entry_dict = prompt_album_selection_or_skip(
                    interaction_data.input_artist, interaction_data.input_track,
                    interaction_data.artist_matches, # Tracks by this artist for album selection
                    interaction_data.is_input_explicitly_live_format,
                    interaction_data.match_threshold,
                    current_library_index, # Full index for listing album tracks
                    PARENTHETICAL_STRIP_REGEX # For normalization within prompt
                )
            elif interaction_data.reason == "no_direct_match_basic_skip_random":
                 print(colorize(f"\nNo direct match for '{interaction_data.input_artist} - {interaction_data.input_track}'. Offering skip/random.", Colors.YELLOW))
                 chosen_match_entry_dict = prompt_user_for_choice(
                    interaction_data.input_artist, interaction_data.input_track,
                    interaction_data.candidates, # Scored (sub-threshold) candidates
                    interaction_data.artist_matches,
                    interaction_data.is_input_explicitly_live_format,
                    interaction_data.match_threshold
                )
            elif interaction_data.reason == "multiple_qualified_matches":
                logging.info(f"MAIN: Multiple qualified matches for '{interaction_data.input_artist} - {interaction_data.input_track}'. Prompting user.")
                chosen_match_entry_dict = prompt_user_for_choice(
                    interaction_data.input_artist, interaction_data.input_track,
                    interaction_data.candidates, # Qualified candidates
                    interaction_data.artist_matches,
                    interaction_data.is_input_explicitly_live_format,
                    interaction_data.match_threshold
                )
            
            if chosen_match_entry_dict: # User made a selection from prompt
                # Prompt functions should return cleaned entries (no temp '_' keys)
                # If not, clean here: chosen_match_entry_dict = {k:v for k,v in chosen_match_entry_dict.items() if not k.startswith('_')}
                print(f"  {Symbols.SUCCESS} {colorize('Matched (Interactive):', Colors.GREEN)} {colorize(Path(chosen_match_entry_dict['path']).name, Colors.MAGENTA)}")
            else: # User skipped or no choice made during interaction
                print(f"  {Symbols.FAILURE} {colorize('Skipped (Interactive):', Colors.RED)} User skipped or no choice made.")
                skipped_track_details_for_file.append(f"{original_input_line} (Reason: Skipped by user or no choice made)")

        elif match_result_obj is not None: # Direct match from service (non-interactive or single best)
            chosen_match_entry_dict = match_result_obj # Already cleaned by MatchingService
            print(f"  {Symbols.SUCCESS} {colorize('Matched (Auto):', Colors.GREEN)} {colorize(Path(chosen_match_entry_dict['path']).name, Colors.MAGENTA)}")
        else: # No match from service, and not interactive, or no interaction path led to a choice
            print(f"  {Symbols.FAILURE} {colorize('Skipped (Auto):', Colors.RED)} No suitable match found by service.")
            skipped_track_details_for_file.append(f"{original_input_line} (Reason: No suitable match found)")

        # If a match was chosen (either auto or interactive), add to M3U lines
        if chosen_match_entry_dict:
            library_service.record_track_usage(chosen_match_entry_dict['path'])
            logging.info(f"APP: Recorded usage for {chosen_match_entry_dict['path']}")
            found_tracks_count += 1
            abs_file_path = Path(chosen_match_entry_dict['path'])
            duration = chosen_match_entry_dict.get('duration', -1)
            # Use matched artist/title if available, fallback to input
            ext_artist = chosen_match_entry_dict.get('artist', input_artist_str) or input_artist_str
            ext_title = chosen_match_entry_dict.get('title', input_title_str) or input_title_str
            try:
                relative_path_to_library = abs_file_path.relative_to(library_abs_path)
                m3u_lines_for_file.append(f"#EXTINF:{duration},{ext_artist} - {ext_title}")
                m3u_lines_for_file.append(relative_path_to_library.as_posix())
            except ValueError: # Path not relative to the library directory
                logging.warning(f"MAIN: Track '{abs_file_path}' not within library directory '{library_abs_path}'. Using absolute path for M3U.")
                m3u_lines_for_file.append(f"#EXTINF:{duration},{ext_artist} - {ext_title}")
                m3u_lines_for_file.append(abs_file_path.as_posix()) # <<< FALLBACK TO ABSOLUTE PATH
                print(f"  {Symbols.WARNING} {colorize('Path Note:', Colors.YELLOW)} Using absolute path for track (not in configured library directory for relative paths).")
        # If chosen_match_entry_dict is None, it was already added to skipped_track_details_for_file or handled by interactive skip message.

    # --- 12. Write Output Files (M3U, Missing Tracks, MPD Copy) ---
    try:
        # Call PlaylistService to handle all file writing
        write_operation_results = playlist_service.write_m3u_and_missing_files(
            m3u_lines_content=m3u_lines_for_file,
            skipped_track_inputs_for_file=skipped_track_details_for_file,
            output_m3u_filepath=full_output_m3u_filepath,
            mpd_playlist_dir_str=final_mpd_playlist_dir_str,
            missing_tracks_dir_path=missing_tracks_dir_abs_path,
            # Use the new variable here:
            input_playlist_path_for_header=source_description_for_missing_header, 
            total_input_tracks=num_input_tracks # num_input_tracks was len(input_track_tuples)
        )

        # --- UI Feedback based on what PlaylistService reported ---
        if write_operation_results.get("m3u_path"):
            print(f"\n{colorize('Generated playlist', Colors.GREEN + Colors.BOLD)} ({found_tracks_count}/{len(input_track_tuples)} tracks): {write_operation_results['m3u_path']}")
        if write_operation_results.get("mpd_copy_path"):
            print(f"{colorize('Copied playlist to MPD directory:', Colors.CYAN)} {write_operation_results['mpd_copy_path']}")
        if write_operation_results.get("mpd_copy_error"): # If service reported an error during MPD copy
            print(colorize(f"Warning: Failed to copy playlist to MPD directory: {write_operation_results['mpd_copy_error']}", Colors.YELLOW), file=sys.stderr)
        
        if write_operation_results.get("missing_file_path"):
            print(f"{colorize('List of missing/skipped tracks saved to:', Colors.YELLOW)} {write_operation_results['missing_file_path']}")
        elif skipped_track_details_for_file : # If there were skips but file wasn't written
             if write_operation_results.get("missing_file_error"): # If service reported an error
                  print(colorize(f"Warning: Failed to write missing tracks file: {write_operation_results['missing_file_error']}", Colors.YELLOW), file=sys.stderr)
             else: # Should not happen if skipped_track_details_for_file is true and no error
                  print(colorize("Warning: Missing tracks list existed but was not written for an unknown reason.", Colors.YELLOW), file=sys.stderr)
        
        # Final summary message
        if skipped_track_details_for_file:
            logging.warning(f"--- Summary: Skipped {len(skipped_track_details_for_file)} tracks. See details in missing tracks file (if written).")
            print(colorize(f"\nWarning: {len(skipped_track_details_for_file)} out of {len(input_track_tuples)} input tracks were skipped.", Colors.YELLOW))
        elif found_tracks_count > 0 : # At least one track included, and no skips
            logging.info("--- Summary: All input tracks were matched and included successfully.")
            print(colorize("\nAll input tracks included successfully.", Colors.GREEN))
        else: # No tracks found, no tracks skipped (e.g., empty input after filtering, or all failed pathing)
            logging.info("--- Summary: No tracks processed or included in the playlist.")
            print(colorize("\nNo tracks were included in the playlist.", Colors.YELLOW))

    except IOError as e: # Catch M3U write failure specifically if raised by service
        print(colorize(f"Error writing M3U playlist: {e}", Colors.RED), file=sys.stderr)
        # Skipped tracks might still be valuable to return for GUI
        return {"success": False, "error": str(e), "skipped_tracks": [line.split(" (Reason:")[0] for line in skipped_track_details_for_file]}
    except Exception as e: # Catch any other unexpected error from service writing phase
        logging.error(f"MAIN: Unexpected error during file writing phase: {e}", exc_info=True)
        print(colorize(f"Unexpected error during file writing: {e}", Colors.RED), file=sys.stderr)
        return {"success": False, "error": str(e), "skipped_tracks": [line.split(" (Reason:")[0] for line in skipped_track_details_for_file]}

    logging.info(f"--- Playlist Maker {constants.VERSION} processing completed. ---")
    print(f"\n{colorize('DONE', Colors.BOLD + Colors.GREEN)}")
    # Return list of original "Artist - Title" lines that were skipped for GUI/caller
    return {"success": True, "skipped_tracks": [line.split(" (Reason:")[0] for line in skipped_track_details_for_file]}

    # Ensure DB is closed before returning successfully
    if library_service: library_service.close_db()
    return {"success": True, "skipped_tracks": [line.split(" (Reason:")[0] for line in skipped_track_details_for_file]}

# Note: The `if __name__ == "__main__":` block that calls `main()` is NOT part of the `main()` function.
# It should be at the very end of app.py, outside any function, if you want app.py to be
# directly executable for some reason (though `python -m playlist_maker.app` is preferred).
# If using `python -m`, that block isn't strictly necessary in app.py as main() is called by the runner.
# However, having a simple runner in `if __name__ == "__main__":` within app.py can be useful for direct testing.
#
# if __name__ == "__main__":
#     # This block would only execute if you run: python playlist_maker/app.py
#     # It's better to use `python -m playlist_maker.app` or a dedicated root runner script.
#     try:
#         run_status = main()
#         if isinstance(run_status, dict) and not run_status.get("success", True):
#             sys.exit(1) # Indicate failure
#         elif isinstance(run_status, int): # If main somehow returns an exit code
#             sys.exit(run_status)
#     except SystemExit as se:
#         sys.exit(se.code) # Propagate sys.exit calls
#     except KeyboardInterrupt:
#         print("\nApplication interrupted by user (Ctrl+C).")
#         sys.exit(130) # Standard exit code for Ctrl+C
#     except Exception as e_top:
#         # This is a last resort catch. Errors should ideally be handled more gracefully within main.
#         logging.getLogger(__name__).critical("Top-level unhandled exception in app.py's __main__ block.", exc_info=True)
#         print(colorize(f"\nCRITICAL UNHANDLED ERROR: {e_top}", Colors.RED + Colors.BOLD), file=sys.stderr)
#         print(colorize("Please check logs for details.", Colors.RED), file=sys.stderr)
#         sys.exit(1) # General error