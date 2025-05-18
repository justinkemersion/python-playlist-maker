# playlist_maker/core/playlist_service.py
import logging
import sys
from pathlib import Path
from datetime import datetime

from playlist_maker.ui.cli_interface import Colors, colorize # For any internal messages if needed

class PlaylistService:
    def __init__(self):
        pass

    def read_input_playlist(self, playlist_file_path_str: str) -> list[tuple[str, str]]:
        """Reads 'Artist - Track' lines, returns list of (artist, title) tuples."""
        tracks = []
        line_num = 0
        try:
            with open(playlist_file_path_str, "r", encoding="utf-8") as f:
                for line in f:
                    line_num += 1
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if " - " in line:
                        artist, track_title = line.split(" - ", 1)
                        tracks.append((artist.strip(), track_title.strip()))
                    else:
                        logging.warning(f"Skipping malformed line {line_num} in '{playlist_file_path_str}': '{line}'")
                        # UI print for this stays in main/caller for now, or main passes a callback
                        # For now, to match old behavior, service might print directly (less ideal)
                        print(colorize(f"Warning (from service): Skipping malformed line {line_num}: '{line}'", Colors.YELLOW), file=sys.stderr)
        except FileNotFoundError:
            logging.error(f"Input playlist file not found: '{playlist_file_path_str}'")
            raise # Let caller (main) handle exit/UI
        except Exception as e:
            logging.error(f"Error reading playlist file '{playlist_file_path_str}': {e}", exc_info=True)
            raise # Let caller (main) handle exit/UI
        return tracks

    def write_m3u_and_missing_files(
        self,
        m3u_lines_content: list[str], # e.g., ["#EXTM3U", "#EXTINF:...", "path", ...]
        skipped_track_inputs_for_file: list[str], # e.g., ["Artist - Title (Reason: ...)"]
        output_m3u_filepath: Path, # Already resolved Path object
        mpd_playlist_dir_str: str | None,
        missing_tracks_dir_path: Path, # Already resolved Path object
        input_playlist_path_for_header: str,
        total_input_tracks: int # For logging/UI context
    ) -> dict: # Returns dict with paths of files written
        """Writes the M3U, missing tracks file, and copies to MPD if specified."""
        
        output_files_info = {"m3u_path": None, "missing_file_path": None, "mpd_copy_path": None}
        found_count_in_m3u = (len(m3u_lines_content) - 1) // 2 if len(m3u_lines_content) > 0 else 0

        # --- Write M3U File ---
        output_dir_for_m3u = output_m3u_filepath.parent
        try:
            output_dir_for_m3u.mkdir(parents=True, exist_ok=True)
            with open(output_m3u_filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(m3u_lines_content) + "\n")
            logging.info(f"PLAYLIST_SVC: Generated playlist '{output_m3u_filepath}' with {found_count_in_m3u}/{total_input_tracks} tracks.")
            output_files_info["m3u_path"] = output_m3u_filepath
        except Exception as e:
            logging.error(f"PLAYLIST_SVC: Failed to write playlist to {output_m3u_filepath}: {e}", exc_info=True)
            # Allow main to print the user-facing error
            raise IOError(f"Failed to write M3U file {output_m3u_filepath}: {e}")

        # --- Optionally copy to MPD playlist directory ---
        if mpd_playlist_dir_str and output_files_info["m3u_path"]: # Only copy if M3U write succeeded
            try:
                mpd_playlist_path_obj = Path(mpd_playlist_dir_str)
                mpd_target_filename = output_m3u_filepath.name # Use same filename
                mpd_final_m3u_path = mpd_playlist_path_obj / mpd_target_filename

                if not mpd_playlist_path_obj.is_dir():
                    if not mpd_playlist_path_obj.exists():
                        logging.info(f"MPD playlist directory '{mpd_playlist_path_obj}' does not exist. Creating.")
                        mpd_playlist_path_obj.mkdir(parents=True, exist_ok=True)
                    else:
                        raise FileNotFoundError(f"MPD path exists but not a directory: {mpd_playlist_path_obj}")
                
                with open(mpd_final_m3u_path, "w", encoding="utf-8") as f_mpd:
                    f_mpd.write("\n".join(m3u_lines_content) + "\n")
                logging.info(f"PLAYLIST_SVC: Copied playlist to MPD directory: {mpd_final_m3u_path}")
                output_files_info["mpd_copy_path"] = mpd_final_m3u_path
            except Exception as e:
                logging.error(f"PLAYLIST_SVC: Failed to copy playlist to MPD dir '{mpd_playlist_dir_str}': {e}", exc_info=True)
                # This is a warning for the user, not a fatal error for the whole process
                output_files_info["mpd_copy_error"] = str(e) # Pass error info back

        # --- Write Missing Tracks File ---
        if skipped_track_inputs_for_file:
            try:
                missing_tracks_dir_path.mkdir(parents=True, exist_ok=True)
                missing_filename_stem = output_m3u_filepath.stem
                missing_filename = f"{missing_filename_stem}-missing-tracks.txt"
                missing_file_full_path = missing_tracks_dir_path / missing_filename

                with open(missing_file_full_path, "w", encoding="utf-8") as f_missing:
                    f_missing.write(f"# Input playlist: {input_playlist_path_for_header}\n")
                    f_missing.write(f"# Generated M3U: {output_m3u_filepath}\n")
                    f_missing.write(f"# Date Generated: {datetime.now().isoformat()}\n")
                    f_missing.write(f"# {len(skipped_track_inputs_for_file)} tracks from input not found/skipped:\n")
                    f_missing.write("-" * 30 + "\n")
                    for missing_track_info in skipped_track_inputs_for_file:
                        f_missing.write(f"{missing_track_info}\n")
                logging.info(f"PLAYLIST_SVC: List of {len(skipped_track_inputs_for_file)} missing tracks saved to: {missing_file_full_path}")
                output_files_info["missing_file_path"] = missing_file_full_path
            except Exception as e:
                logging.error(f"PLAYLIST_SVC: Failed to write missing tracks file to {missing_tracks_dir_path}: {e}", exc_info=True)
                output_files_info["missing_file_error"] = str(e) # Pass error info back
        
        return output_files_info