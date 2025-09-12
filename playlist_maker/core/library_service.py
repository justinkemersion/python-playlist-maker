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
from . import constants

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
        """
        Initialize the LibraryService with a SQLite database connection.
        
        Args:
            db_path: Path to the SQLite database file for caching library metadata
            
        The service will attempt to connect to the database and create necessary tables.
        If the connection fails, the service will still function but without caching.
        """
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

    def _create_tables_if_not_exist(self):
        if not self.cursor: return
        try:
            # Library Tracks Table (existing)
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

            # --- MODIFIED: Track Usage Stats Table ---
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS track_usage_stats (
                    library_track_path TEXT PRIMARY KEY,
                    times_added_to_playlist INTEGER DEFAULT 0,
                    last_added_timestamp INTEGER
                    -- REMOVED: FOREIGN KEY (library_track_path) REFERENCES library_tracks(path) ON DELETE CASCADE
                )
            """)
            # Index on library_track_path is implicitly created by PRIMARY KEY
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_times_added ON track_usage_stats (times_added_to_playlist);")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_last_added ON track_usage_stats (last_added_timestamp);")
            # --- END MODIFICATION ---

            self.conn.commit()
            logging.debug("LIB_SVC: Ensured library_tracks and track_usage_stats tables and indexes exist.")
        except sqlite3.Error as e:
            logging.error(f"LIB_SVC: Error creating tables or indexes: {e}", exc_info=True)

    # ... (get_file_metadata, _add_or_update_track_in_db, _get_cached_tracks_mtimes, _load_track_from_db_row are unchanged) ...
    def get_file_metadata(self, file_path_obj: Path) -> tuple[str, str, str, int | None]:
        """
        Extract metadata from an audio file using mutagen.
        
        Args:
            file_path_obj: Path to the audio file
            
        Returns:
            Tuple of (artist, title, album, duration_in_seconds)
            Duration will be None if not available or if there's an error
        """
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
    
    # playlist_maker/core/library_service.py
# ... (imports and other parts of the class up to scan_library) ...

    def scan_library(self, scan_library_path_str: str, supported_extensions: tuple,
                     live_album_keywords_regex, parenthetical_strip_regex, # These regex are from main
                     force_rescan: bool = False, use_cache: bool = True) -> bool:
        self.library_index_memory = [] # Reset in-memory index for this scan call
        scan_errors = 0

        # ... (path resolution and initial setup as before) ...
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

        cache_active = use_cache and self.conn is not None
        if use_cache and not self.conn:
            logging.warning("LIB_SVC: Cache enabled but DB connection failed. Performing full in-memory scan.")

        print(f"\n{colorize('Scanning Music Library:', Colors.CYAN)}")
        print(f"{Symbols.INFO} Path: {colorize(str(scan_library_path), Colors.MAGENTA)}")
        scan_type_msg = "Forcing full rescan, rebuilding index..." if force_rescan and cache_active else \
                        "Updating library index (using cache)..." if cache_active else \
                        "Performing full library scan (cache disabled or unavailable)..."
        print(colorize(scan_type_msg, Colors.BLUE))
        
        start_time = time.time()
        processed_fs_files_count = 0
        new_or_updated_in_db_count = 0
        db_tracks_removed_count = 0 # Counts tracks removed from library_tracks
        stats_tracks_pruned_count = 0 # New counter for stats
        update_interval_progress = constants.DEFAULT_PROGRESS_UPDATE_INTERVAL
        
        # First pass: count total files for better progress indication
        print(colorize("Counting files in library...", Colors.BLUE))
        total_files_count = 0
        for root, _, files in os.walk(scan_library_path, followlinks=True):
            for file_name in files:
                if file_name.lower().endswith(supported_extensions):
                    total_files_count += 1
        print(f"{Symbols.INFO} Found {total_files_count} audio files to process.")

        cached_mtimes = {}
        if cache_active and not force_rescan:
            logging.debug("LIB_SVC: Loading mtimes from cache...")
            cached_mtimes = self._get_cached_tracks_mtimes()
            logging.debug(f"LIB_SVC: Loaded {len(cached_mtimes)} mtime entries from cache.")
        elif force_rescan and cache_active:
            logging.info("LIB_SVC: Force rescan requested. Clearing existing library_tracks table.")
            try:
                self.cursor.execute("DELETE FROM library_tracks;")
                # Note: We are NOT deleting from track_usage_stats here. That will be handled by pruning later.
                self.conn.commit()
                logging.info("LIB_SVC: Force rescan: library_tracks table cleared.")
            except sqlite3.Error as e:
                logging.error(f"LIB_SVC: Failed to clear library_tracks table for rescan: {e}", exc_info=True)
        
        current_filesystem_paths = set()

        # --- Main os.walk loop to populate/update library_tracks and library_index_memory ---
        # This loop remains largely the same as the one you had with force_rescan logic inside it
        # for deciding whether to process a file or load from (old) cache.
        # When force_rescan is true, track_data_for_memory_index is always None initially, forcing reprocessing.
        for root, _, files in os.walk(scan_library_path, followlinks=True):
            root_path = Path(root)
            for file_name in files:
                if not file_name.lower().endswith(supported_extensions):
                    continue
                
                processed_fs_files_count += 1
                if processed_fs_files_count % update_interval_progress == 0 or processed_fs_files_count == total_files_count:
                    progress_percent = (processed_fs_files_count / total_files_count * 100) if total_files_count > 0 else 0
                    print(f"\r{Symbols.INFO} Processing: {processed_fs_files_count}/{total_files_count} files ({progress_percent:.1f}%)", end="", flush=True)

                file_path_obj = root_path / file_name
                try:
                    abs_file_path_str = str(file_path_obj.resolve())
                    file_mtime = int(os.path.getmtime(abs_file_path_str))
                except (OSError, FileNotFoundError) as e:
                    logging.warning(f"LIB_SVC: Could not access/stat {file_path_obj}: {e}. Skipping.")
                    scan_errors += 1
                    continue
                
                current_filesystem_paths.add(abs_file_path_str)
                track_data_for_memory_index: dict | None = None

                if cache_active and not force_rescan and abs_file_path_str in cached_mtimes:
                    if cached_mtimes[abs_file_path_str] == file_mtime:
                        try:
                            self.cursor.execute("SELECT * FROM library_tracks WHERE path = ?", (abs_file_path_str,))
                            row = self.cursor.fetchone()
                            if row:
                                track_data_for_memory_index = self._load_track_from_db_row(row)
                            else:
                                logging.warning(f"LIB_SVC: Cache inconsistency for {abs_file_path_str}. Reprocessing.")
                        except sqlite3.Error as e:
                            logging.error(f"LIB_SVC: DB error fetching cached {abs_file_path_str}: {e}. Reprocessing.", exc_info=True)
                
                if track_data_for_memory_index is None: # Needs processing (not cached, changed, or force_rescan)
                    new_or_updated_in_db_count += 1
                    # ... (metadata extraction, normalization, _add_or_update_track_in_db call as before) ...
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
                            self._add_or_update_track_in_db(track_db_entry) # This adds/replaces in library_tracks
                        
                        track_data_for_memory_index = {k:v for k,v in track_db_entry.items() if k != 'file_modified_timestamp'}
                    except Exception as e_proc:
                        logging.error(f"LIB_SVC: Error processing file {file_path_obj}: {e_proc}", exc_info=True)
                        scan_errors += 1
                        continue

                if track_data_for_memory_index:
                    self.library_index_memory.append(track_data_for_memory_index)
        # --- End of os.walk loop ---

        if cache_active: self.conn.commit() # Commit all DB changes to library_tracks from the loop

        # --- Pruning logic for track_usage_stats if force_rescan was used ---
        if force_rescan and cache_active and self.conn and self.cursor:
            logging.info("LIB_SVC: Force rescan: Pruning track_usage_stats for paths no longer in the rebuilt library_tracks...")
            try:
                # Get all paths currently in track_usage_stats
                self.cursor.execute("SELECT library_track_path FROM track_usage_stats")
                stats_paths = {row['library_track_path'] for row in self.cursor.fetchall()}

                # Get all paths now in the (rebuilt) library_tracks table
                # No need to query library_tracks again, use current_filesystem_paths which represents
                # all valid processed paths if force_rescan built everything anew.
                # However, if some files failed processing during rescan, they wouldn't be in current_filesystem_paths
                # OR in library_index_memory. A direct query from the library_tracks table is safer.
                self.cursor.execute("SELECT path FROM library_tracks")
                current_library_db_paths = {row['path'] for row in self.cursor.fetchall()}
                
                paths_to_delete_from_stats = list(stats_paths - current_library_db_paths)

                if paths_to_delete_from_stats:
                    delete_batch_stats = [(p,) for p in paths_to_delete_from_stats]
                    self.cursor.executemany("DELETE FROM track_usage_stats WHERE library_track_path = ?", delete_batch_stats)
                    self.conn.commit() # Commit this specific pruning
                    stats_tracks_pruned_count = len(paths_to_delete_from_stats)
                    logging.info(f"LIB_SVC: Pruned {stats_tracks_pruned_count} orphaned entries from track_usage_stats after force rescan.")
                else:
                    logging.info("LIB_SVC: No orphaned entries found in track_usage_stats to prune after force rescan.")
            except sqlite3.Error as e:
                logging.error(f"LIB_SVC: Error pruning track_usage_stats after force rescan: {e}", exc_info=True)

        # --- Remove tracks from DB (and stats) that are no longer on filesystem (for non-force_rescan case) ---
        if cache_active: # This block handles regular scans or cases where force_rescan might not have cleared everything.
            paths_in_db_lib_tracks = set(self._get_cached_tracks_mtimes().keys()) # Paths currently in library_tracks
            deleted_paths_on_disk = paths_in_db_lib_tracks - current_filesystem_paths
            
            if deleted_paths_on_disk:
                delete_batch_lib = [(p,) for p in deleted_paths_on_disk]
                try:
                    # Delete from library_tracks
                    self.cursor.executemany("DELETE FROM library_tracks WHERE path = ?", delete_batch_lib)
                    db_tracks_removed_count = self.cursor.rowcount if self.cursor.rowcount != -1 else len(delete_batch_lib)
                    logging.info(f"LIB_SVC: Removed {db_tracks_removed_count} tracks from library_tracks (no longer on filesystem).")

                    # --- MODIFICATION: Explicitly delete from track_usage_stats ---
                    # The paths in delete_batch_lib are the ones to remove from stats as well
                    self.cursor.executemany("DELETE FROM track_usage_stats WHERE library_track_path = ?", delete_batch_lib)
                    deleted_stats_count = self.cursor.rowcount if self.cursor.rowcount != -1 else 0 # Approximate
                    if not force_rescan: # Only add to stats_tracks_pruned_count if not a force_rescan (where it's counted separately)
                         stats_tracks_pruned_count += deleted_stats_count
                    logging.info(f"LIB_SVC: Explicitly removed {deleted_stats_count} corresponding entries from track_usage_stats.")
                    # --- END MODIFICATION ---

                    self.conn.commit()
                except sqlite3.Error as e:
                    logging.error(f"LIB_SVC: Error removing deleted tracks/stats from DB cache: {e}", exc_info=True)


        # --- UI Print Footer & Summary ---
        scan_duration = time.time() - start_time
        print(f"\n{colorize('Scan complete.', Colors.GREEN)} ({scan_duration:.2f}s)")
        
        if cache_active:
            print(f"  {Symbols.INFO} Filesystem items checked: {processed_fs_files_count}")
            print(f"  {Symbols.ARROW} New/updated tracks processed: {new_or_updated_in_db_count}")
            if db_tracks_removed_count > 0: # Tracks removed from library_tracks
                print(f"  {Symbols.FAILURE} Tracks removed from library cache (deleted from disk): {db_tracks_removed_count}")
            if stats_tracks_pruned_count > 0: # Stats entries pruned
                 print(f"  {Symbols.INFO} Usage stats entries pruned (for deleted/missing tracks): {stats_tracks_pruned_count}")

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

    # ... (get_library_index, record_track_usage, get_track_usage_stats, close_db remain as previously defined) ...
    # Ensure `_add_or_update_track_in_db`, `_get_cached_tracks_mtimes`, `_load_track_from_db_row` are present
    # and also `record_track_usage` and `get_track_usage_stats`
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
            """, track_data)
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
            "duration": row['duration'] if row['duration'] is not None else -1,
            "filename_stem": row['filename_stem'],
            "norm_artist_stripped": row['norm_artist_stripped'],
            "norm_title_stripped": row['norm_title_stripped'],
            "norm_filename_stripped": row['norm_filename_stripped'],
            "entry_is_live": bool(row['entry_is_live'])
        }

    def get_library_index(self) -> list[dict]:
        """
        Get the in-memory library index for track matching.
        
        Returns:
            List of dictionaries containing track metadata for matching operations
        """
        return self.library_index_memory

    def record_track_usage(self, library_track_path: str):
        """
        Record that a track was added to a playlist for usage statistics.
        
        Args:
            library_track_path: Full path to the track file
        """
        if not self.cursor or not self.conn:
            logging.warning(f"LIB_SVC: DB not available, cannot record usage for '{library_track_path}'.")
            return
        current_timestamp = int(time.time())
        try:
            # Direct UPSERT, assuming library_track_path exists in library_tracks.
            # If library_track_path could be invalid, a SELECT 1 FROM library_tracks check first is safer.
            # However, record_track_usage should only be called for paths confirmed to be in the library.
            self.cursor.execute("""
                INSERT INTO track_usage_stats (library_track_path, times_added_to_playlist, last_added_timestamp)
                VALUES (?, 1, ?)
                ON CONFLICT(library_track_path) DO UPDATE SET
                    times_added_to_playlist = times_added_to_playlist + 1,
                    last_added_timestamp = excluded.last_added_timestamp;
            """, (library_track_path, current_timestamp))
            self.conn.commit()
            logging.debug(f"LIB_SVC: Recorded usage for track '{library_track_path}'.")
        except sqlite3.Error as e:
            logging.error(f"LIB_SVC: Error recording track usage for '{library_track_path}': {e}", exc_info=True)

    def get_track_usage_stats(self, library_track_path: str) -> dict | None:
        if not self.cursor:
            logging.warning(f"LIB_SVC: DB not available, cannot get usage stats for '{library_track_path}'.")
            return None
        try:
            self.cursor.execute("SELECT * FROM track_usage_stats WHERE library_track_path = ?", (library_track_path,))
            row = self.cursor.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            logging.error(f"LIB_SVC: Error getting track usage stats for '{library_track_path}': {e}", exc_info=True)
            return None

    def close_db(self):
        if self.conn:
            try:
                self.conn.commit()
                self.conn.close()
                logging.info("LIB_SVC: Closed library index DB connection.")
                self.conn = None
                self.cursor = None
            except sqlite3.Error as e:
                logging.error(f"LIB_SVC: Error closing DB connection: {e}", exc_info=True)