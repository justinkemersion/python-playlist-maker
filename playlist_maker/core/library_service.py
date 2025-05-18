# playlist_maker/core/library_service.py
import os
import sys
import mutagen
import mutagen.mp3
import mutagen.flac
import mutagen.oggvorbis
import mutagen.mp4
from pathlib import Path
import logging
import time

# Import normalization functions from their new location
from playlist_maker.utils.normalization_utils import (
    normalize_and_detect_specific_live_format,
    check_album_for_live_indicators
)
# Import UI elements for progress and messages directly within scan_library
from playlist_maker.ui.cli_interface import Colors, Symbols, colorize

# Pandas import for duration (as in original file)
try:
    import pandas as pd
    logging.debug("Pandas library found and imported for LibraryService.")
except ImportError:
    class DummyPandas: # Keep the dummy pandas for when it's not installed
        def isna(self, val):
            if val is None: return True
            try: return val != val
            except TypeError: return False
    pd = DummyPandas()
    logging.info("Pandas library not found for LibraryService; using basic duration checks.")


class LibraryService:
    def __init__(self):
        self.library_index = []
        # PARENTHETICAL_STRIP_REGEX and live_album_keywords_regex will need to be passed
        # to scan_library or set on the instance if they are always the same for a service instance.
        # For now, scan_library will take them as parameters.

    def get_file_metadata(self, file_path_obj: Path): # file_path_obj is already a Path
        """Extracts Artist, Title, Album, Duration from an audio file."""
        artist, title, album, duration = "", "", "", None
        try:
            audio = mutagen.File(file_path_obj, easy=True)
            detailed_audio = mutagen.File(file_path_obj)

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
                    if not pd.isna(duration_float):
                        duration = int(duration_float)
                except (ValueError, TypeError):
                    duration = None

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
            artist, title, album, duration = artist or "", title or "", album or "", duration or None
        return artist, title, album, duration

    def scan_library(self, scan_library_path_str: str, supported_extensions: tuple,
                     live_album_keywords_regex, parenthetical_strip_regex): # Added regex params
        """Scans the library path, extracts metadata, and builds the index."""
        self.library_index = [] # Reset index for a new scan
        try:
            scan_library_path = Path(scan_library_path_str).resolve(strict=True)
        except FileNotFoundError:
            logging.error(f"Scan library path does not exist: {scan_library_path_str}")
            print(colorize(f"Error: Scan library path does not exist: {scan_library_path_str}", Colors.RED), file=sys.stderr)
            # Instead of sys.exit, we should let the caller (main) handle this,
            # perhaps by raising an exception or returning a status.
            # For now, we'll print and return False to indicate failure to main.
            return False # Indicate scan failure
        except Exception as e:
            logging.error(f"Error resolving scan library path {scan_library_path_str}: {e}")
            print(colorize(f"Error: Could not resolve scan library path {scan_library_path_str}: {e}", Colors.RED), file=sys.stderr)
            return False # Indicate scan failure

        print(f"\n{colorize('Scanning Music Library:', Colors.CYAN)}")
        print(f"{Symbols.INFO} Path: {colorize(str(scan_library_path), Colors.MAGENTA)}")
        start_time = time.time()
        processed_count = 0
        scan_errors = 0
        update_interval = 500

        for root, _, files in os.walk(scan_library_path, followlinks=True):
            root_path = Path(root)
            for file in files:
                if file.lower().endswith(supported_extensions):
                    processed_count += 1
                    if processed_count % update_interval == 0:
                        print(f"{colorize('.', Colors.BLUE)}", end="", flush=True)

                    file_path = root_path / file
                    try:
                        if not os.access(file_path, os.R_OK):
                            logging.warning(f"Skipping inaccessible file during scan: {file_path}")
                            scan_errors += 1
                            continue

                        abs_file_path = file_path.resolve()
                        # Call the instance method for get_file_metadata
                        meta_artist, meta_title, meta_album, meta_duration = self.get_file_metadata(abs_file_path)

                        # Use imported normalization functions, passing the necessary regex
                        norm_title_match_str, title_has_live_format = normalize_and_detect_specific_live_format(meta_title, parenthetical_strip_regex)
                        norm_artist_match_str, _ = normalize_and_detect_specific_live_format(meta_artist, parenthetical_strip_regex)
                        norm_filename_match_str, filename_has_live_format = normalize_and_detect_specific_live_format(file_path.stem, parenthetical_strip_regex)
                        album_indicates_live = check_album_for_live_indicators(meta_album, live_album_keywords_regex, parenthetical_strip_regex)

                        current_entry_is_live = title_has_live_format or filename_has_live_format or album_indicates_live

                        if meta_album and album_indicates_live and not (title_has_live_format or filename_has_live_format) :
                            logging.debug(f"Track '{meta_title}' on album '{meta_album}' marked as LIVE due to album keywords. Path: {abs_file_path}")

                        self.library_index.append({
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
        
        print("\nScan complete.") # Ensure this prints after dots if any
        print() # Newline after dots or if no dots
        end_time = time.time()
        scan_duration = end_time - start_time

        if not self.library_index:
            print(f"{Symbols.FAILURE} {colorize('Scan Failed.', Colors.RED)} No tracks found in {scan_duration:.2f}s.")
            # We'll return False to indicate failure, main can handle exit or further action
        else:
            print(f"{Symbols.SUCCESS} {colorize('Scan Complete.', Colors.GREEN)} Found {colorize(str(len(self.library_index)), Colors.BOLD)} tracks in {scan_duration:.2f}s.")

        if scan_errors > 0:
            print(f"  {Symbols.WARNING} {colorize(f'Encountered {scan_errors} errors during scan. Check log for details.', Colors.YELLOW)}")
        print(f"{Colors.CYAN}{'-'*45}{Colors.RESET}") # Match original output style

        # Log scan errors (original logic)
        if scan_errors > 0: # This logging was slightly different from the print
            logging.warning(f"Encountered {scan_errors} errors during scan (check log for details).")
        
        if not self.library_index:
            logging.error("Library scan resulted in 0 recognized tracks.")
            return False # Indicate scan failure

        return True # Indicate scan success

    def get_library_index(self):
        # Provide a way to access the index after scanning
        return self.library_index