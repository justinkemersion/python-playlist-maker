# playlist_maker/ui/argument_parser.py
import argparse
from pathlib import Path
from playlist_maker.core import constants # Import the constants module
from .cli_interface import Colors # Relative import as it's in the same 'ui' package

def parse_arguments(argv_list=None):
    parser = argparse.ArgumentParser(
        description=f"{Colors.BOLD}Generate M3U playlists by matching 'Artist - Track' lines against a music library.{Colors.RESET}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- Input Source Group (Playlist File OR AI Prompt) ---
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument(
        "playlist_file", 
        nargs='?', # Makes it optional within the group context
        default=None, 
        help="Input text file (one 'Artist - Track' per line). Used if --ai-prompt is not."
    )
    input_source_group.add_argument(
        "--ai-prompt",
        type=str,
        default=None, # Explicitly default to None
        help="Generate initial playlist using an AI prompt (e.g., 'Make me a sad indie folk playlist'). "
             "This generates an 'Artist - Song' list that then gets processed. Overrides playlist_file."
    )

    # --- AI Specific Arguments ---
    ai_group = parser.add_argument_group('AI Playlist Generation Options (used with --ai-prompt)')
    ai_group.add_argument(
        "--ai-model",
        type=str,
        default=None, # Will use config or constant default if --ai-prompt is used
        help=(f"Specify the AI model to use (e.g., gpt-4-turbo-preview). "
              f"Cfg: AI.model, PyDef: {constants.DEFAULT_AI_MODEL}")
    )
    # Consider adding --ai-api-key here if you want to allow CLI override of config/env for key

    # --- General Options (copied from your existing parser) ---
    parser.add_argument("-l", "--library", default=None, help=f"Music library path. Cfg: Paths.library, Def: {constants.DEFAULT_SCAN_LIBRARY}")
    # ... (all your other existing parser.add_argument calls for -o, -m, -t, etc.)
    parser.add_argument("--mpd-music-dir", default=None, help=f"MPD music_directory path. Cfg: Paths.mpd_music_dir, Def: {constants.DEFAULT_MPD_MUSIC_DIR_CONF}")
    parser.add_argument("-o", "--output-dir", default=None, help=f"Output dir for M3U. Cfg: Paths.output_dir, Def: {constants.DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--missing-dir", default=None, help=f"Dir for missing tracks list. Cfg: Paths.missing_dir, Def: {constants.DEFAULT_MISSING_TRACKS_DIR}")
    parser.add_argument("-m", "--mpd-playlist-dir", default=None, nargs='?', const="USE_DEFAULT_OR_CONFIG",
                        help="Copy M3U to MPD dir. No value=use default/config. Cfg: Paths.mpd_playlist_dir")
    parser.add_argument("-t", "--threshold", type=int, default=None, choices=range(0, 101), metavar="[0-100]",
                        help=f"Min match score [0-100]. Cfg: Matching.threshold, Def: {constants.DEFAULT_MATCH_THRESHOLD}")
    parser.add_argument("--live-penalty", type=float, default=None, metavar="[0.0-1.0]",
                        help=f"Penalty for unwanted live match. Cfg: Matching.live_penalty, Def: {constants.DEFAULT_LIVE_PENALTY_FACTOR}")
    parser.add_argument(
        "--output-name-format",
        default=None,
        type=str,
        help=(
            "Custom format string for the output M3U filename. "
            "Placeholders: {basename}, {basename:transforms}, {YYYY}, {YY}, {MM}, {DD}, {hh}, {mm}, {ss}. "
            "Transforms for basename (e.g., {basename:cp}): "
            "'c'-capitalize words, 'u'-uppercase, 'l'-lowercase; "
            "'p'-prettify spaces, 's'-hyphenate, '_'-underscorify. "
            f"Example: \"{{basename:cp}}_{{YYYY}}-{{MM}}-{{DD}}.m3u\" (Configurable, PyDef: {constants.DEFAULT_OUTPUT_NAME_FORMAT})"
        )
    )
    parser.add_argument("--log-file", type=Path, default=None, help=f"Log file path. Cfg: Logging.log_file, Def: <project_root>/{constants.DEFAULT_LOG_FILE_NAME}")
    parser.add_argument("--log-mode", choices=['append', 'overwrite'], default=None, help="Log file mode. Cfg: Logging.log_mode, Def: overwrite")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=None, help="Log level for file. Cfg: Logging.log_level, Def: INFO")
    parser.add_argument("-e", "--extensions", nargs='+', default=None, help=f"Audio extensions. Cfg: General.extensions, Def: {' '.join(constants.DEFAULT_SUPPORTED_EXTENSIONS)}")
    parser.add_argument("--live-album-keywords", nargs='+', default=None, help="Regex patterns for live albums. Cfg: Matching.live_album_keywords")
    parser.add_argument("--strip-keywords", nargs='+', default=None, help="Keywords to strip from (). Cfg: Matching.strip_keywords")
    parser.add_argument("-i", "--interactive", action="store_true", default=None, help="Enable interactive mode. Cfg: General.interactive, Def: false")
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {constants.SCRIPT_VERSION}',
        help="Show program's version number and exit."
    )

    if argv_list is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(argv_list)

    # Validation for mutually exclusive group is implicitly handled by `required=True`
    # on the group. If neither playlist_file (positional, now optional due to nargs='?')
    # nor --ai-prompt is given, argparse will error.
    # If both are somehow given (shouldn't happen with mutually_exclusive_group unless positional nargs='?' interacts weirdly),
    # you might add an explicit check, but the group should prevent it.
    # The main check `if not args.ai_prompt and not args.playlist_file:` is now redundant due to group.

    return args