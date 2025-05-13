# --- playlist_maker_gui.py ---

import tkinter as tk
from tkinter import ttk
from tkinter import filedialog, messagebox, scrolledtext
import threading
import queue
import logging
import sys
import os
from datetime import datetime # Keep this for Option B

from playlist_maker import main as pm_main
from playlist_maker import Colors # Still useful for other GUI elements potentially
from playlist_maker import (
    DEFAULT_SCAN_LIBRARY, DEFAULT_OUTPUT_DIR, DEFAULT_MPD_MUSIC_DIR_CONF,
    DEFAULT_MPD_PLAYLIST_DIR_CONF,
    DEFAULT_MATCH_THRESHOLD, DEFAULT_LIVE_PENALTY_FACTOR
)

class TkinterLogHandler(logging.Handler):
    """Custom logging handler to redirect logs to a Tkinter Text/ScrolledText widget with colors."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue.Queue()

        # Define color tags in the text widget
        self.text_widget.tag_config("DEBUG", foreground="gray")
        self.text_widget.tag_config("INFO", foreground="black")
        self.text_widget.tag_config("WARNING", foreground="#E69138") # Orange
        self.text_widget.tag_config("ERROR", foreground="red", font=("TkDefaultFont", 9, "bold"))
        self.text_widget.tag_config("CRITICAL", foreground="white", background="red", font=("TkDefaultFont", 9, "bold")) # Corrected from my last version
        self.text_widget.tag_config("TIMESTAMP", foreground="#512E5F") # Dark Purple

        self.text_widget.after(100, self.poll_log_queue)

    def emit(self, record: logging.LogRecord): # Correctly expects LogRecord
        self.queue.put(record) # Puts the LogRecord object on the queue

    def poll_log_queue(self):
        try:
            while True:
                record = self.queue.get(block=False) # 'record' IS a LogRecord here

                timestamp_str = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
                log_message = record.getMessage()
                level_name_tag = record.levelname

                effective_tag = level_name_tag
                # Check if the tag for this level name is configured.
                # A simpler check might be if tag_cget returns a non-empty string for 'foreground'.
                # However, just trying to use it is fine as Tkinter won't error if tag is undefined, just won't apply style.
                # For robustness, we could pre-check or have a default.
                if level_name_tag not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                    # If it's an unknown level, use INFO styling as a fallback
                    effective_tag = "INFO"
                    # Log only once about unknown tags to avoid flooding
                    if not hasattr(self, '_warned_unknown_tags'): self._warned_unknown_tags = set()
                    if level_name_tag not in self._warned_unknown_tags:
                        logging.debug(f"GUI Log Handler: Unknown log level '{level_name_tag}' received, using INFO style.")
                        self._warned_unknown_tags.add(level_name_tag)

                self.text_widget.configure(state='normal')
                self.text_widget.insert(tk.END, f"{timestamp_str} - ", "TIMESTAMP")
                self.text_widget.insert(tk.END, f"{record.levelname}", effective_tag) # Apply level tag
                self.text_widget.insert(tk.END, f" - {log_message}\n")
                self.text_widget.configure(state='disabled')
                self.text_widget.see(tk.END)
                self.text_widget.update_idletasks()
        except queue.Empty:
            pass
        finally:
            self.text_widget.after(100, self.poll_log_queue)

class PlaylistMakerGUI:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("Playlist Maker GUI")

        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ... (Input Frame and Options Frame setup as in your file) ...
        input_frame = tk.LabelFrame(main_frame, text="Paths & Files", padx=10, pady=10)
        input_frame.pack(fill=tk.X, pady=(0,10))

        row_idx = 0
        tk.Label(input_frame, text="Playlist File:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.playlist_file_entry = tk.Entry(input_frame, width=60)
        self.playlist_file_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        tk.Button(input_frame, text="Browse...", command=self.browse_playlist).grid(row=row_idx, column=2, padx=5, pady=2)
        input_frame.columnconfigure(1, weight=1)

        row_idx += 1
        tk.Label(input_frame, text="Music Library Path:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.library_path_entry = tk.Entry(input_frame, width=60)
        self.library_path_entry.insert(0, os.path.expanduser(DEFAULT_SCAN_LIBRARY))
        self.library_path_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        tk.Button(input_frame, text="Browse...", command=self.browse_library).grid(row=row_idx, column=2, padx=5, pady=2)

        row_idx += 1
        tk.Label(input_frame, text="MPD Music Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.mpd_music_dir_entry = tk.Entry(input_frame, width=60)
        self.mpd_music_dir_entry.insert(0, os.path.expanduser(DEFAULT_MPD_MUSIC_DIR_CONF))
        self.mpd_music_dir_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        tk.Button(input_frame, text="Browse...", command=lambda: self.browse_directory(self.mpd_music_dir_entry)).grid(row=row_idx, column=2, padx=5, pady=2)

        row_idx += 1
        tk.Label(input_frame, text="Output Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_dir_entry = tk.Entry(input_frame, width=60)
        self.output_dir_entry.insert(0, DEFAULT_OUTPUT_DIR) # Already relative, no expanduser needed here for default
        self.output_dir_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        tk.Button(input_frame, text="Browse...", command=self.browse_output).grid(row=row_idx, column=2, padx=5, pady=2)

        # --- Options Frame ---
        options_frame = tk.LabelFrame(main_frame, text="Options", padx=10, pady=10)
        options_frame.pack(fill=tk.X, pady=(0,10))

        matching_options_frame = tk.Frame(options_frame)
        matching_options_frame.pack(fill=tk.X)

        tk.Label(matching_options_frame, text="Match Threshold (0-100):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.threshold_var = tk.IntVar(value=DEFAULT_MATCH_THRESHOLD)
        self.threshold_spinbox = tk.Spinbox(matching_options_frame, from_=0, to=100, textvariable=self.threshold_var, width=5)
        self.threshold_spinbox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        tk.Label(matching_options_frame, text="Live Penalty (0.0-1.0):").grid(row=0, column=2, sticky=tk.W, padx=(20,5), pady=2)
        self.live_penalty_var = tk.DoubleVar(value=DEFAULT_LIVE_PENALTY_FACTOR)
        self.live_penalty_spinbox = tk.Spinbox(matching_options_frame, from_=0.0, to=1.0, increment=0.05, format="%.2f", textvariable=self.live_penalty_var, width=5)
        self.live_penalty_spinbox.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)

        general_options_frame = tk.Frame(options_frame)
        general_options_frame.pack(fill=tk.X, pady=(5,0))

        self.interactive_var = tk.BooleanVar() # Defaults to False
        tk.Checkbutton(general_options_frame, text="Use Console Interactive Mode (CLI Prompts)", variable=self.interactive_var).grid(row=0, column=0, sticky=tk.W, columnspan=2, pady=2)

        self.copy_to_mpd_var = tk.BooleanVar() # Defaults to False
        self.mpd_copy_check = tk.Checkbutton(general_options_frame, text="Copy to MPD Playlist Dir:", variable=self.copy_to_mpd_var, command=self.toggle_mpd_path_entry)
        self.mpd_copy_check.grid(row=1, column=0, sticky=tk.W, pady=2)

        self.mpd_playlist_dir_entry = tk.Entry(general_options_frame, width=45, state=tk.DISABLED)
        self.mpd_playlist_dir_entry.insert(0, os.path.expanduser(DEFAULT_MPD_PLAYLIST_DIR_CONF))
        self.mpd_playlist_dir_entry.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=2)
        self.mpd_playlist_browse_button = tk.Button(general_options_frame, text="Browse...", command=lambda: self.browse_directory(self.mpd_playlist_dir_entry), state=tk.DISABLED)
        self.mpd_playlist_browse_button.grid(row=1, column=2, padx=5, pady=2)
        general_options_frame.columnconfigure(1, weight=1)

        logging_options_frame = tk.Frame(options_frame)
        logging_options_frame.pack(fill=tk.X, pady=(5,0))
        tk.Label(logging_options_frame, text="File Log Level:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.log_level_var = tk.StringVar(value="INFO")
        self.log_level_combo = ttk.Combobox(logging_options_frame, textvariable=self.log_level_var,
                                            values=["DEBUG", "INFO", "WARNING", "ERROR"], state="readonly", width=10)
        self.log_level_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)


        action_frame = tk.Frame(main_frame, pady=5)
        action_frame.pack(fill=tk.X)
        self.generate_button = tk.Button(action_frame, text="Generate Playlist", command=self.run_generate_playlist_thread, width=20, height=2)
        self.generate_button.pack(pady=5)

        log_frame = tk.LabelFrame(main_frame, text="Log Output", padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text_area = scrolledtext.ScrolledText(log_frame, height=15, width=80, state='disabled', wrap=tk.WORD)
        self.log_text_area.pack(fill=tk.BOTH, expand=True)

        # Call setup_gui_logging which creates and configures TkinterLogHandler
        self.setup_gui_logging()

    def toggle_mpd_path_entry(self):
        if self.copy_to_mpd_var.get():
            self.mpd_playlist_dir_entry.config(state=tk.NORMAL)
            self.mpd_playlist_browse_button.config(state=tk.NORMAL)
        else:
            self.mpd_playlist_dir_entry.config(state=tk.DISABLED)
            self.mpd_playlist_browse_button.config(state=tk.DISABLED)

    def setup_gui_logging(self):
        """Redirects Python's logging to the Tkinter text area using custom formatting."""
        gui_log_handler = TkinterLogHandler(self.log_text_area) # Creates handler, which sets up tags
        # NO formatter is set on this handler externally, as it does its own.
        gui_log_handler.setLevel(logging.DEBUG) # Handler itself will process DEBUG and above

        root_logger = logging.getLogger()
        # Prevent adding handler multiple times if setup_gui_logging might be called again
        if not any(isinstance(h, TkinterLogHandler) for h in root_logger.handlers):
            root_logger.addHandler(gui_log_handler)

        # Ensure the root logger itself will pass messages of the desired level.
        if root_logger.level == 0 or root_logger.level > logging.DEBUG: # Level 0 is NOTSET (effectively passes all)
             root_logger.setLevel(logging.DEBUG)


    def browse_playlist(self):
        file = filedialog.askopenfilename(
            title="Select Playlist File",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*"))
        )
        if file:
            self.playlist_file_entry.delete(0, tk.END)
            self.playlist_file_entry.insert(0, file)

    def browse_directory(self, entry_widget):
        path = filedialog.askdirectory(title="Select Directory")
        if path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, path)

    def browse_library(self):
        self.browse_directory(self.library_path_entry)

    def browse_output(self):
        self.browse_directory(self.output_dir_entry)

    def run_generate_playlist_thread(self):
        playlist_file = self.playlist_file_entry.get()
        if not playlist_file:
            messagebox.showerror("Input Error", "Please select a playlist file.")
            return

        self.log_text_area.configure(state='normal')
        self.log_text_area.delete('1.0', tk.END)
        # These initial messages will also be picked up by TkinterLogHandler if root logger level is low enough
        logging.info("GUI: Starting playlist generation...")
        logging.info("GUI: This may take a while for large libraries (scan step).")
        if self.interactive_var.get():
            logging.info("GUI: CONSOLE INTERACTIVE MODE is enabled. Prompts will appear in the terminal.")
        self.log_text_area.configure(state='disabled')

        self.generate_button.config(text="Generating...", state=tk.DISABLED)
        thread = threading.Thread(target=self.execute_playlist_maker, daemon=True)
        thread.start()

    def execute_playlist_maker(self):
        try:
            argv = [self.playlist_file_entry.get()]

            for arg_name, entry_widget in [
                ("--library", self.library_path_entry),
                ("--mpd-music-dir", self.mpd_music_dir_entry),
                ("--output-dir", self.output_dir_entry)
            ]:
                path = entry_widget.get()
                if path.strip(): argv.extend([arg_name, path.strip()])

            threshold = self.threshold_var.get()
            argv.extend(["--threshold", str(threshold)])

            live_penalty = self.live_penalty_var.get()
            argv.extend(["--live-penalty", f"{live_penalty:.2f}"])

            if self.interactive_var.get():
                argv.append("--interactive")

            if self.copy_to_mpd_var.get():
                mpd_playlist_path = self.mpd_playlist_dir_entry.get()
                if mpd_playlist_path.strip():
                    argv.extend(["--mpd-playlist-dir", mpd_playlist_path.strip()])
                else:
                    argv.append("--mpd-playlist-dir")

            log_level = self.log_level_var.get()
            if log_level: argv.extend(["--log-level", log_level])

            logging.info(f"GUI: Running backend with args: {argv}")
            result = pm_main(argv_list=argv)

            if result and result.get("success"):
                logging.info("GUI: Playlist generation process completed successfully!")
                skipped_tracks = result.get("skipped_tracks", [])
                if skipped_tracks:
                    logging.warning("\n--- Skipped/Missing Tracks ---")
                    for item in skipped_tracks:
                        logging.warning(f"  - {item}") # These will be orange
                    logging.warning(f"Total skipped/missing: {len(skipped_tracks)}. See missing-tracks.txt if saved.")
                else:
                    logging.info("GUI: All tracks from input were matched and included!")
            elif result and result.get("error"):
                error_msg = result.get("error", "Unknown error from playlist maker.")
                logging.error(f"GUI: Playlist maker reported an error: {error_msg}") # Red & bold
                self.root.after(0, lambda err_val=error_msg: messagebox.showerror("Playlist Maker Error", err_val))
            else:
                logging.critical("GUI: Received unexpected or no result from playlist maker process.") # White on Red & bold
                self.root.after(0, lambda: messagebox.showerror("Process Error", "Playlist maker did not return a clear status."))

        except ValueError as ve:
            logging.error(f"GUI: Error from playlist maker (ValueError): {ve}")
            self.root.after(0, lambda err_val=str(ve): messagebox.showerror("Playlist Maker Error", err_val))
        except Exception as e:
            logging.error(f"GUI: Unexpected error during playlist generation: {e}", exc_info=True)
            self.root.after(0, lambda err_val=str(e): messagebox.showerror("Generation Error", err_val))
        finally:
            self.root.after(0, lambda: self.generate_button.config(text="Generate Playlist", state=tk.NORMAL))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s (%(name)s) - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logging.info("GUI_MAIN: Initializing PlaylistMakerGUI...")

    root = tk.Tk()
    app = PlaylistMakerGUI(root)

    logging.info("GUI_MAIN: Starting Tkinter main loop.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logging.info("GUI_MAIN: KeyboardInterrupt received, shutting down GUI.")
        print("\nPlaylist Maker GUI closed via Ctrl+C.")
    finally:
        logging.info("GUI_MAIN: Tkinter main loop finished or interrupted.")