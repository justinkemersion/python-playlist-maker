# playlist_maker/ui/argument_parser.py
import argparse
from pathlib import Path
from playlist_maker.core import constants 
from .cli_interface import Colors 

def parse_arguments(argv_list=None):
    parser = argparse.ArgumentParser(
        description=f"{Colors.BOLD}Generate M3U playlists by matching 'Artist - Track' lines against a music library.{Colors.RESET}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    input_source_group = parser.add_mutually_exclusive_group(required=True)
    # ... (playlist_file and --ai-prompt arguments as before) ...
    input_source_group.add_argument(
        "playlist_file", 
        nargs='?', 
        default=None, 
        help="Input text file (one 'Artist - Track' per line). Used if --ai-prompt is not."
    )
    input_source_group.add_argument(
        "--ai-prompt",
        type=str,
        default=None,
        help="Generate initial playlist using an AI prompt..."
    )

    ai_group = parser.add_argument_group('AI Playlist Generation Options (used with --ai-prompt)')
    ai_group.add_argument(
        "--ai-model",
        type=str,
        default=None, 
        help=(f"Specify the AI model to use... Cfg: AI.model, PyDef: {constants.DEFAULT_AI_MODEL}")
    )

    # --- General Options ---
    parser.add_argument("-l", "--library", default=None, help=f"Music library path. Cfg: Paths.library, Def: {constants.DEFAULT_SCAN_LIBRARY}")
    parser.add_argument("--mpd-music-dir", default=None, help=f"MPD music_directory path. Cfg: Paths.mpd_music_dir, Def: {constants.DEFAULT_MPD_MUSIC_DIR_CONF}")
    parser.add_argument("-o", "--output-dir", default=None, help=f"Output dir for M3U. Cfg: Paths.output_dir, Def: {constants.DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--missing-dir", default=None, help=f"Dir for missing tracks list. Cfg: Paths.missing_dir, Def: {constants.DEFAULT_MISSING_TRACKS_DIR}")
    parser.add_argument("-m", "--mpd-playlist-dir", default=None, nargs='?', const="USE_DEFAULT_OR_CONFIG", help="Copy M3U to MPD dir...")
    parser.add_argument("-t", "--threshold", type=int, default=None, choices=range(0, 101), metavar="[0-100]", help=f"Min match score... Def: {constants.DEFAULT_MATCH_THRESHOLD}")
    parser.add_argument("--live-penalty", type=float, default=None, metavar="[0.0-1.0]", help=f"Penalty for unwanted live match... Def: {constants.DEFAULT_LIVE_PENALTY_FACTOR}")
    parser.add_argument("--output-name-format", default=None, type=str, help="Custom format string for the output M3U filename...")
    parser.add_argument("--log-file", type=Path, default=None, help=f"Log file path... Def: <project_root>/{constants.DEFAULT_LOG_FILE_NAME}")
    parser.add_argument("--log-mode", choices=['append', 'overwrite'], default=None, help="Log file mode...")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=None, help="Log level for file...")
    parser.add_argument("-e", "--extensions", nargs='+', default=None, help=f"Audio extensions... Def: {' '.join(constants.DEFAULT_SUPPORTED_EXTENSIONS)}")
    parser.add_argument("--live-album-keywords", nargs='+', default=None, help="Regex patterns for live albums...")
    parser.add_argument("--strip-keywords", nargs='+', default=None, help="Keywords to strip from ()..")
    
    parser.add_argument( # THIS IS THE NEW --force-rescan ARGUMENT
        "--force-rescan",
        action="store_true",
        default=False, 
        help="Force a full library rescan, ignoring and rebuilding the persistent cache if enabled."
    )
    # THIS IS THE SINGLE, CORRECT DEFINITION FOR -i / --interactive
    parser.add_argument(
        "-i", "--interactive", 
        action="store_true", 
        default=None, # So we can distinguish between not set and explicitly set to False by config
        help="Enable interactive mode. Cfg: General.interactive, Def: false"
    )
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

    return args