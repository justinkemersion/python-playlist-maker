# playlist_maker/core/library_service.py
import sqlite3
import os
import sys # For sys.stderr in UI prints within service
import time
from pathlib import Path
import logging
import mutagen # Ensure all mutagen submodules are imported if needed by get_file_metadata
import mutagen.mp3, mutagen.flac, mutagen.oggvorbis, mutagen.mp4

from playlist_maker.utils.normalization_utils import (
    normalize_and_detect_specific_live_format,
    check_album_for_live_indicators
)
from playlist_maker.ui.cli_interface import Colors, Symbols, colorize

try:
    import pandas as pd
except ImportError:
    class DummyPandas:
        def isna(self, val):
            if val is None: return True
            try: return val != val
            except TypeError: return False
    pd = DummyPandas()
    logging.info("LIB_SVC: Pandas not found, using dummy for duration checks.")

class LibraryService:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.library_index_memory: list[dict] = [] # For MatchingService
        self._connect_db() # Try to connect on init
        if self.conn: # Only create tables if connection succeeded
            self._create_tables_if_not_exist()
        else:
            logging.error("LIB_SVC: Database connection failed on init. Cache will be unavailable.")


    def _connect_db(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True) # Ensure 'data' dir exists
            self.conn = sqlite3.connect(self.db_path, timeout=10) # Added timeout
            self.conn.row_factory = sqlite3.Row # Access columns by name
            self.cursor = self.conn.cursor()
            self.conn.execute("PRAGMA journal_mode=WAL;") # For better concurrency & performance
            logging.info(f"LIB_SVC: Connected to library index DB: {self.db_path}")
        except sqlite3.Error as e:
            logging.error(f"LIB_SVC: Error connecting to library index DB {self.db_path}: {e}", exc_info=True)
            self.conn = None # Ensure conn is None if connection fails
            self.cursor = None
            # Do not raise here, allow scan_library to fallback or fail if cache is essential

    def _create_tables_if_not_exist(self):
        if not self.cursor: return
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS library_tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    artist TEXT, title TEXT, album TEXT, duration INTEGER,
                    filename_stem TEXT,
                    norm_artist_stripped TEXT, norm_title_stripped TEXT, norm_filename_stripped TEXT,
                    entry_is_live BOOLEAN,
                    file_modified_timestamp INTEGER NOT NULL
                )
            """)
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_lib_path ON library_tracks (path);")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_lib_norm_artist ON library_tracks (norm_artist_stripped);")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_lib_norm_title ON library_tracks (norm_title_stripped);")
            self.conn.commit()
            logging.debug("LIB_SVC: Ensured library_tracks table and indexes exist.")
        except sqlite3.Error as e:
            logging.error(f"LIB_SVC: Error creating library_tracks table or indexes: {e}", exc_info=True)

    def get_file_metadata(self, file_path_obj: Path) -> tuple[str, str, str, int | None]:
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
                    if not pd.isna(duration_float): duration = int(duration_float)
                except (ValueError, TypeError): duration = None
            # logging for missing tags can be done here if desired
        except mutagen.MutagenError as me:
            logging.debug(f"LIB_SVC: Mutagen error reading {file_path_obj}: {me}")
        except Exception as e:
            logging.warning(f"LIB_SVC: Could not read metadata for {file_path_obj} due to {type(e).__name__}: {e}", exc_info=False)
        return artist, title, album, duration

    def _add_or_update_track_in_db(self, track_data: dict):
        if not self.cursor: 
            logging.warning("LIB_SVC: DB cursor not available, cannot update cache for {track_data['path']}")
            return
        try:
            self.cursor.execute("""
                INSERT OR REPLACE INTO library_tracks (
                    path, artist, title, album, duration, filename_stem,
                    norm_artist_stripped, norm_title_stripped, norm_filename_stripped,
                    entry_is_live, file_modified_timestamp
                ) VALUES (:path, :artist, :title, :album, :duration, :filename_stem,
                          :norm_artist_stripped, :norm_title_stripped, :norm_filename_stripped,
                          :entry_is_live, :file_modified_timestamp)
            """, track_data) # Use named placeholders with dict
            # self.conn.commit() # Commit can be done in batches or at the end of scan for performance
        except sqlite3.Error as e:
            logging.error(f"LIB_SVC: Error inserting/updating track {track_data.get('path')} in DB: {e}", exc_info=True)

    def _get_cached_tracks_mtimes(self) -> dict[str, int]:
        if not self.cursor: return {}
        cached_files = {}
        try:
            for row in self.cursor.execute("SELECT path, file_modified_timestamp FROM library_tracks"):
                cached_files[row['path']] = row['file_modified_timestamp']
        except sqlite3.Error as e:
            logging.error(f"LIB_SVC: Error fetching cached track mtimes: {e}", exc_info=True)
        return cached_files

    def _load_track_from_db_row(self, row: sqlite3.Row) -> dict:
        return {
            "path": row['path'], "artist": row['artist'], "title": row['title'], "album": row['album'],
            "duration": row['duration'] if row['duration'] is not None else -1, # Ensure -1 for None
            "filename_stem": row['filename_stem'],
            "norm_artist_stripped": row['norm_artist_stripped'],
            "norm_title_stripped": row['norm_title_stripped'],
            "norm_filename_stripped": row['norm_filename_stripped'],
            "entry_is_live": bool(row['entry_is_live'])
        }

    def scan_library(self, scan_library_path_str: str, supported_extensions: tuple,
                     live_album_keywords_regex, parenthetical_strip_regex, # These regex are from main
                     force_rescan: bool = False, use_cache: bool = True) -> bool:
        self.library_index_memory = [] # Reset in-memory index for this scan call
        scan_errors = 0

        try:
            scan_library_path = Path(scan_library_path_str).resolve(strict=True)
        except FileNotFoundError:
            logging.error(f"LIB_SVC: Scan library path does not exist: {scan_library_path_str}")
            print(colorize(f"Error: Scan library path does not exist: {scan_library_path_str}", Colors.RED), file=sys.stderr)
            return False
        except Exception as e:
            logging.error(f"LIB_SVC: Error resolving scan library path {scan_library_path_str}: {e}", exc_info=True)
            print(colorize(f"Error: Could not resolve scan library path {scan_library_path_str}: {e}", Colors.RED), file=sys.stderr)
            return False

        # Check DB connection if cache is enabled
        cache_active = use_cache and self.conn is not None
        if use_cache and not self.conn:
            logging.warning("LIB_SVC: Cache enabled but DB connection failed. Performing full in-memory scan.")

        # UI Print Header
        print(f"\n{colorize('Scanning Music Library:', Colors.CYAN)}")
        print(f"{Symbols.INFO} Path: {colorize(str(scan_library_path), Colors.MAGENTA)}")
        scan_type_msg = "Forcing full rescan, rebuilding index..." if force_rescan and cache_active else \
                        "Updating library index (using cache)..." if cache_active else \
                        "Performing full library scan (cache disabled or unavailable)..."
        print(colorize(scan_type_msg, Colors.BLUE))
        
        start_time = time.time()
        processed_fs_files_count = 0
        new_or_updated_in_db_count = 0
        db_tracks_removed_count = 0
        update_interval_dots = 500 # Print dot every N files

        cached_mtimes = {}
        if cache_active and not force_rescan:
            logging.debug("LIB_SVC: Loading mtimes from cache...")
            cached_mtimes = self._get_cached_tracks_mtimes()
            logging.debug(f"LIB_SVC: Loaded {len(cached_mtimes)} mtime entries from cache.")
        elif force_rescan and cache_active:
            logging.info("LIB_SVC: Force rescan requested. Clearing existing library_tracks table.")
            try:
                self.cursor.execute("DELETE FROM library_tracks;")
                self.conn.commit() # Commit the delete
            except sqlite3.Error as e:
                logging.error(f"LIB_SVC: Failed to clear library_tracks table for rescan: {e}", exc_info=True)
                # Proceed with scan, but duplicates might occur if INSERT OR REPLACE fails
        
        current_filesystem_paths = set() # To track files currently on disk for cleanup

        for root, _, files in os.walk(scan_library_path, followlinks=True):
            root_path = Path(root)
            for file_name in files:
                if not file_name.lower().endswith(supported_extensions):
                    continue
                
                processed_fs_files_count += 1
                if processed_fs_files_count % update_interval_dots == 0:
                    print(colorize(".", Colors.BLUE), end="", flush=True)

                file_path_obj = root_path / file_name
                try:
                    abs_file_path_str = str(file_path_obj.resolve())
                    file_mtime = int(os.path.getmtime(abs_file_path_str))
                except (OSError, FileNotFoundError) as e: # File might have disappeared during walk
                    logging.warning(f"LIB_SVC: Could not access/stat {file_path_obj}: {e}. Skipping.")
                    scan_errors += 1
                    continue
                
                current_filesystem_paths.add(abs_file_path_str) # Add to set of existing files
                track_data_for_memory_index: dict | None = None

                # Decision: Process file or use cached data?
                if cache_active and not force_rescan and abs_file_path_str in cached_mtimes:
                    if cached_mtimes[abs_file_path_str] == file_mtime:
                        # File is cached and mtime matches: load from DB for in-memory index
                        try:
                            self.cursor.execute("SELECT * FROM library_tracks WHERE path = ?", (abs_file_path_str,))
                            row = self.cursor.fetchone()
                            if row:
                                track_data_for_memory_index = self._load_track_from_db_row(row)
                            else: # Inconsistency: in mtime cache but not DB. Reprocess.
                                logging.warning(f"LIB_SVC: Cache inconsistency for {abs_file_path_str}. Reprocessing.")
                                # Fall through to process_and_cache_file block
                        except sqlite3.Error as e:
                            logging.error(f"LIB_SVC: DB error fetching cached {abs_file_path_str}: {e}. Reprocessing.", exc_info=True)
                            # Fall through
                
                if track_data_for_memory_index is None: # Needs processing (not cached, changed, or force_rescan)
                    new_or_updated_in_db_count += 1
                    try:
                        meta_artist, meta_title, meta_album, meta_duration = self.get_file_metadata(file_path_obj)
                        
                        norm_title_str, title_has_live_format = normalize_and_detect_specific_live_format(meta_title, parenthetical_strip_regex)
                        norm_artist_str, _ = normalize_and_detect_specific_live_format(meta_artist, parenthetical_strip_regex)
                        norm_filename_str, filename_has_live_format = normalize_and_detect_specific_live_format(file_path_obj.stem, parenthetical_strip_regex)
                        album_indicates_live = check_album_for_live_indicators(meta_album, live_album_keywords_regex, parenthetical_strip_regex)
                        is_live = title_has_live_format or filename_has_live_format or album_indicates_live

                        track_db_entry = {
                            "path": abs_file_path_str, "artist": meta_artist, "title": meta_title, "album": meta_album,
                            "duration": meta_duration if meta_duration is not None else -1,
                            "filename_stem": file_path_obj.stem,
                            "norm_artist_stripped": norm_artist_str, "norm_title_stripped": norm_title_str,
                            "norm_filename_stripped": norm_filename_str, "entry_is_live": is_live,
                            "file_modified_timestamp": file_mtime
                        }
                        if cache_active:
                            self._add_or_update_track_in_db(track_db_entry)
                        
                        # Prepare data for in-memory index (without mtime)
                        track_data_for_memory_index = {k:v for k,v in track_db_entry.items() if k != 'file_modified_timestamp'}

                    except Exception as e_proc: # Catch errors during metadata/normalization for a single file
                        logging.error(f"LIB_SVC: Error processing file {file_path_obj}: {e_proc}", exc_info=True)
                        scan_errors += 1
                        continue # Skip this file
                
                if track_data_for_memory_index:
                    self.library_index_memory.append(track_data_for_memory_index)

        if cache_active: self.conn.commit() # Commit all DB changes from the loop

        # Remove tracks from DB that are no longer on filesystem
        if cache_active: # No need to do this if cache wasn't used or on force_rescan (table was cleared)
            paths_in_db = set(self._get_cached_tracks_mtimes().keys()) # Get current state of DB paths
            deleted_paths_on_disk = paths_in_db - current_filesystem_paths
            if deleted_paths_on_disk:
                db_tracks_removed_count = len(deleted_paths_on_disk)
                try:
                    delete_batch = [(p,) for p in deleted_paths_on_disk] # List of tuples for executemany
                    self.cursor.executemany("DELETE FROM library_tracks WHERE path = ?", delete_batch)
                    self.conn.commit()
                    logging.info(f"LIB_SVC: Removed {db_tracks_removed_count} tracks from DB cache (no longer on filesystem).")
                except sqlite3.Error as e:
                    logging.error(f"LIB_SVC: Error removing deleted tracks from DB cache: {e}", exc_info=True)

        # --- UI Print Footer & Summary ---
        scan_duration = time.time() - start_time
        print(f"\n{colorize('Scan complete.', Colors.GREEN)} ({scan_duration:.2f}s)")
        
        if cache_active:
            print(f"  {Symbols.INFO} Filesystem items checked: {processed_fs_files_count}")
            print(f"  {Symbols.ARROW} New/updated tracks processed: {new_or_updated_in_db_count}")
            if db_tracks_removed_count > 0:
                print(f"  {Symbols.FAILURE} Tracks removed from cache (deleted from disk): {db_tracks_removed_count}")
        
        if not self.library_index_memory:
            print(f"{Symbols.FAILURE} {colorize('Scan Result:', Colors.RED)} No tracks found or loaded into index.")
            logging.warning("LIB_SVC: Library scan resulted in an empty in-memory index.")
            return False
        else:
            print(f"{Symbols.SUCCESS} {colorize('Scan Result:', Colors.GREEN)} {len(self.library_index_memory)} tracks loaded into library index.")

        if scan_errors > 0:
            print(f"  {Symbols.WARNING} {colorize(f'Encountered {scan_errors} errors during scan. Check log for details.', Colors.YELLOW)}")
            logging.warning(f"LIB_SVC: Encountered {scan_errors} errors during scan.")
        print(f"{Colors.CYAN}{'-'*45}{Colors.RESET}")
        return True

    def get_library_index(self) -> list[dict]:
        return self.library_index_memory

    def close_db(self):
        if self.conn:
            try:
                self.conn.commit() # Final commit
                self.conn.close()
                logging.info("LIB_SVC: Closed library index DB connection.")
                self.conn = None
                self.cursor = None
            except sqlite3.Error as e:
                logging.error(f"LIB_SVC: Error closing DB connection: {e}", exc_info=True)