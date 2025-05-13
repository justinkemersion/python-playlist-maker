import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext # Use scrolledtext for better logging
import threading
import queue # For thread-safe GUI updates from logger
import logging # To configure logging handler
import sys
import io # To capture stdout/stderr

# Assuming playlist_maker.py is in the same directory or Python path
# Assuming playlist_maker.py is in the same directory or Python path
from playlist_maker import main as pm_main          # Import the main function
from playlist_maker import Colors                  # Import Colors
from playlist_maker import DEFAULT_SCAN_LIBRARY, \
                           DEFAULT_OUTPUT_DIR, \
                           DEFAULT_MPD_MUSIC_DIR_CONF # Import defaults
# You might need to import other constants used in the GUI if playlist_maker.py defines them

class TkinterLogHandler(logging.Handler):
    """Custom logging handler to redirect logs to a Tkinter Text/ScrolledText widget."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue.Queue()
        # Start a poller to process messages from the queue
        self.text_widget.after(100, self.poll_log_queue)

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg) # Put log message into queue

    def poll_log_queue(self):
        try:
            while True: # Process all messages currently in queue
                record = self.queue.get(block=False)
                self.text_widget.configure(state='normal')
                self.text_widget.insert(tk.END, record + '\n')
                self.text_widget.configure(state='disabled')
                self.text_widget.see(tk.END) # Scroll to the end
                self.text_widget.update_idletasks() # Ensure GUI updates
        except queue.Empty:
            pass # Queue is empty
        finally:
            # Reschedule the poller
            self.text_widget.after(100, self.poll_log_queue)

class PlaylistMakerGUI:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("Playlist Maker GUI")

        # --- Main Frame ---
        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Input Frame ---
        input_frame = tk.LabelFrame(main_frame, text="Paths & Files", padx=10, pady=10)
        input_frame.pack(fill=tk.X, pady=(0,10))

        row_idx = 0
        tk.Label(input_frame, text="Playlist File:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.playlist_file_entry = tk.Entry(input_frame, width=60)
        self.playlist_file_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        tk.Button(input_frame, text="Browse...", command=self.browse_playlist).grid(row=row_idx, column=2, padx=5, pady=2)
        input_frame.columnconfigure(1, weight=1) # Make entry expand

        row_idx += 1
        tk.Label(input_frame, text="Music Library Path:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.library_path_entry = tk.Entry(input_frame, width=60)
        self.library_path_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        self.library_path_entry.insert(0, DEFAULT_SCAN_LIBRARY) # Pre-fill with default
        tk.Button(input_frame, text="Browse...", command=self.browse_library).grid(row=row_idx, column=2, padx=5, pady=2)

        row_idx += 1
        tk.Label(input_frame, text="MPD Music Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.mpd_music_dir_entry = tk.Entry(input_frame, width=60)
        self.mpd_music_dir_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        self.mpd_music_dir_entry.insert(0, DEFAULT_MPD_MUSIC_DIR_CONF)
        tk.Button(input_frame, text="Browse...", command=lambda: self.browse_directory(self.mpd_music_dir_entry)).grid(row=row_idx, column=2, padx=5, pady=2)


        row_idx += 1
        tk.Label(input_frame, text="Output Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_dir_entry = tk.Entry(input_frame, width=60)
        self.output_dir_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=2)
        self.output_dir_entry.insert(0, DEFAULT_OUTPUT_DIR) # Pre-fill
        tk.Button(input_frame, text="Browse...", command=self.browse_output).grid(row=row_idx, column=2, padx=5, pady=2)


        # --- Options Frame (Example - can be expanded) ---
        options_frame = tk.LabelFrame(main_frame, text="Options", padx=10, pady=10)
        options_frame.pack(fill=tk.X, pady=(0,10))

        self.interactive_var = tk.BooleanVar()
        tk.Checkbutton(options_frame, text="Run in Console Interactive Mode (CLI Prompts)", variable=self.interactive_var).pack(anchor=tk.W)
        # Add more options here: threshold, log level dropdown, etc.
        # For now, we'll rely on playlist_maker.conf for other settings


        # --- Action Frame ---
        action_frame = tk.Frame(main_frame, pady=5)
        action_frame.pack(fill=tk.X)
        self.generate_button = tk.Button(action_frame, text="Generate Playlist", command=self.run_generate_playlist_thread, width=20, height=2)
        self.generate_button.pack(pady=5)

        # --- Log Area Frame ---
        log_frame = tk.LabelFrame(main_frame, text="Log Output", padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text_area = scrolledtext.ScrolledText(log_frame, height=15, width=80, state='disabled', wrap=tk.WORD)
        self.log_text_area.pack(fill=tk.BOTH, expand=True)

        # Setup logging to redirect to our text widget
        self.setup_gui_logging()

    def setup_gui_logging(self):
        """Redirects Python's logging to the Tkinter text area."""
        gui_log_handler = TkinterLogHandler(self.log_text_area)
        # You can set a specific format for the GUI log messages if desired
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        gui_log_handler.setFormatter(formatter)
        gui_log_handler.setLevel(logging.INFO) # Or DEBUG for more verbosity in GUI

        # Get the root logger from playlist_maker.py (or the global root logger)
        # It's better if playlist_maker.py's setup_logging defines a named logger
        # and we add our handler to that. For now, add to root.
        logging.getLogger().addHandler(gui_log_handler)
        # Ensure CLI's console logger doesn't conflict or duplicate too much
        # This is tricky; the best way is to make playlist_maker.py aware if it's run by GUI
        # For now, just adding handler.


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
        self.log_text_area.delete('1.0', tk.END) # Clear previous logs
        self.log_text_area.insert(tk.END, "Starting playlist generation...\n")
        self.log_text_area.insert(tk.END, "This may take a while for large libraries (scan step).\n")
        self.log_text_area.insert(tk.END, "Check console if interactive mode is enabled and prompts appear there.\n")
        self.log_text_area.configure(state='disabled')

        self.generate_button.config(text="Generating...", state=tk.DISABLED)

        # Start generation in a new thread
        thread = threading.Thread(target=self.execute_playlist_maker, daemon=True)
        thread.start()

        # Check thread status periodically (optional, for more complex UI updates)
        # self.root.after(100, lambda: self.check_thread(thread))

    def execute_playlist_maker(self):
        """Constructs args and calls the main playlist_maker script logic."""
        try:
            # Construct argv for playlist_maker.main()
            argv = [self.playlist_file_entry.get()] # Positional argument first

            lib_path = self.library_path_entry.get()
            if lib_path: argv.extend(["--library", lib_path])

            mpd_dir = self.mpd_music_dir_entry.get()
            if mpd_dir: argv.extend(["--mpd-music-dir", mpd_dir])

            out_dir = self.output_dir_entry.get()
            if out_dir: argv.extend(["--output-dir", out_dir])

            if self.interactive_var.get():
                argv.append("--interactive")

            # Add more args based on other GUI fields if you add them
            # e.g., argv.extend(["--threshold", self.threshold_entry.get()])

            # Inform the user what's being run
            # Cannot use logger here directly as it's in another thread.
            # Use the queue mechanism by calling log_to_gui
            self.log_to_gui(f"Running with args: {argv}", level="INFO")

            # Call the main function from playlist_maker.py
            # This will use its own config file loading and default handling for args not specified by GUI
            pm_main(argv_list=argv)

            self.log_to_gui("Playlist generation process completed successfully!", level="INFO", color=Colors.GREEN)
            # No need for messagebox on success if logs are clear.
            # messagebox.showinfo("Success", "Playlist generation process finished!")

        # In playlist-maker-gui.py, inside the `execute_playlist_maker` method's `except Exception as e:` block:

        except Exception as e:
            error_msg_for_log = f"Error during playlist generation: {e}"
            # Logging an exception object with exc_info=True gives traceback in log file
            logging.error(error_msg_for_log, exc_info=True) # Use Python's logger for GUI errors too

            # To ensure log_to_gui gets called from the GUI's main thread if it updates UI
            self.root.after(0, lambda msg=error_msg_for_log: self.log_to_gui(msg, level="ERROR")) # Pass a copy of the message

            # Capture the current string value of e for the deferred messagebox
            error_str_for_messagebox = str(e)
            self.root.after(0, lambda err_val=error_str_for_messagebox: messagebox.showerror("Generation Error", err_val))
        finally:
            # Re-enable button in the main thread
            self.root.after(0, lambda: self.generate_button.config(text="Generate Playlist", state=tk.NORMAL))

    def log_to_gui(self, message, level="INFO", color=None):
        """Helper to put messages onto the log handler's queue from this thread."""
        # This mimics how the logging handler would do it
        # Ideally, the playlist_maker's own logging should be fully captured.
        # This is more for direct GUI status updates from the GUI thread.
        if hasattr(self, 'log_handler_queue'): # Ensure handler and queue exist
            formatted_message = f"{level}: {message}"
            if color:
                 # The TkinterLogHandler does not handle color directly from here.
                 # Color needs to be embedded if logger not configured to strip/handle it.
                 # Or, TkinterLogHandler could be enhanced to use tags for colors.
                 # For now, it will be plain from here.
                 pass
            self.log_handler_queue.put(formatted_message)
        else: # Fallback if handler not fully set up yet
             self.root.after(0, lambda: self._direct_log_insert(f"{level}: {message}\n"))

    def _direct_log_insert(self, message): # Internal helper for direct insertion
        self.log_text_area.configure(state='normal')
        self.log_text_area.insert(tk.END, message)
        self.log_text_area.configure(state='disabled')
        self.log_text_area.see(tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    app = PlaylistMakerGUI(root)
    # Store the queue for log_to_gui if handler created
    for handler in logging.getLogger().handlers:
         if isinstance(handler, TkinterLogHandler):
             app.log_handler_queue = handler.queue
             break
    root.mainloop()