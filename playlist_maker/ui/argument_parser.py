# playlist_maker/ui/argument_parser.py
import argparse
from pathlib import Path
# from playlist_maker import ( # DELETE THIS OLD IMPORT BLOCK
#     DEFAULT_SCAN_LIBRARY, DEFAULT_MPD_MUSIC_DIR_CONF, DEFAULT_OUTPUT_DIR,
#     DEFAULT_MISSING_TRACKS_DIR, DEFAULT_MATCH_THRESHOLD, DEFAULT_LIVE_PENALTY_FACTOR,
#     DEFAULT_LOG_FILE_NAME, DEFAULT_SUPPORTED_EXTENSIONS, SCRIPT_VERSION
# )
from playlist_maker.core import constants # Import the constants module
from .cli_interface import Colors

def parse_arguments(argv_list=None):
    parser = argparse.ArgumentParser(
        description=f"{Colors.BOLD}Generate M3U playlists by matching 'Artist - Track' lines against a music library.{Colors.RESET}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Update help strings to use constants.WHATEVER
    parser.add_argument("playlist_file", help="Input text file (one 'Artist - Track' per line).")
    parser.add_argument("-l", "--library", default=None, help=f"Music library path. Cfg: Paths.library, Def: {constants.DEFAULT_SCAN_LIBRARY}")
    parser.add_argument("--mpd-music-dir", default=None, help=f"MPD music_directory path. Cfg: Paths.mpd_music_dir, Def: {constants.DEFAULT_MPD_MUSIC_DIR_CONF}")
    parser.add_argument("-o", "--output-dir", default=None, help=f"Output dir for M3U. Cfg: Paths.output_dir, Def: {constants.DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--missing-dir", default=None, help=f"Dir for missing tracks list. Cfg: Paths.missing_dir, Def: {constants.DEFAULT_MISSING_TRACKS_DIR}")
    parser.add_argument("-m", "--mpd-playlist-dir", default=None, nargs='?', const="USE_DEFAULT_OR_CONFIG",
                        help="Copy M3U to MPD dir. No value=use default/config. Cfg: Paths.mpd_playlist_dir") # Default for this is complex, help is fine
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
            f"Example: \"{{basename:cp}}_{{YYYY}}-{{MM}}-{{DD}}.m3u\" (Configurable, Python default: {constants.DEFAULT_OUTPUT_NAME_FORMAT})"
        )
    )
    parser.add_argument("--log-file", type=Path, default=None, help=f"Log file path. Cfg: Logging.log_file, Def: <project_root>/{constants.DEFAULT_LOG_FILE_NAME}")
    parser.add_argument("--log-mode", choices=['append', 'overwrite'], default=None, help="Log file mode. Cfg: Logging.log_mode, Def: overwrite") # Default is from config
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=None, help="Log level for file. Cfg: Logging.log_level, Def: INFO") # Default is from config
    parser.add_argument("-e", "--extensions", nargs='+', default=None, help=f"Audio extensions. Cfg: General.extensions, Def: {' '.join(constants.DEFAULT_SUPPORTED_EXTENSIONS)}")
    # For live_album_keywords and strip_keywords, the defaults are lists of regex/strings, maybe too long for help.
    # The current help is fine as it just says "Cfg: Matching.live_album_keywords"
    parser.add_argument("--live-album-keywords", nargs='+', default=None, help="Regex patterns for live albums. Cfg: Matching.live_album_keywords")
    parser.add_argument("--strip-keywords", nargs='+', default=None, help="Keywords to strip from (). Cfg: Matching.strip_keywords")
    parser.add_argument("-i", "--interactive", action="store_true", default=None, help="Enable interactive mode. Cfg: General.interactive, Def: false") # Default is from config
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {constants.SCRIPT_VERSION}', # Use constants.SCRIPT_VERSION
        help="Show program's version number and exit."
    )

    if argv_list is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(argv_list)
    return args