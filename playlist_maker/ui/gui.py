# playlist_maker_gui.py (at project root)

import tkinter as tk
# from tkinter import ttk # No longer need direct ttk if using ttkbootstrap's version
from tkinter import filedialog, messagebox, scrolledtext, font
import ttkbootstrap as ttk # <--- IMPORT TTKBOOTSTRAP as ttk
from ttkbootstrap.constants import * # For styles like SUCCESS, INFO, DANGER for buttons etc.

import threading
import queue
import logging
import sys
import os
from datetime import datetime
from pathlib import Path # For SCRIPT_DIR if used for sys.path

# --- Crucial Imports for New Structure ---
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# --- Crucial Imports for New Structure (Now relative or package-absolute) ---
try:
    from ..app import main as pm_main_cli             # Relative: from parent dir's app.py
    from ..core import constants as pm_constants      # Relative: from parent dir's core.constants
    from .cli_interface import Colors                # Relative: from same dir's cli_interface.py
    # OR Absolute from package root:
    # from playlist_maker.app import main as pm_main_cli
    # from playlist_maker.core import constants as pm_constants
    # from playlist_maker.ui.cli_interface import Colors
except ImportError as e:
    # ... (Error handling for imports as before, but the paths are different now) ...
    # This block becomes less likely to be hit if your package structure is sound.
    logging.critical(f"GUI: CRITICAL IMPORT ERROR inside package: {e}", exc_info=True)
    # Showing a Tkinter messagebox here if Tk itself fails to import due to this is tricky.
    # The process might just exit.
    print(f"CRITICAL ERROR: Cannot load GUI components due to import failure: {e}", file=sys.stderr)
    sys.exit(1)

# --- TkinterLogHandler (no changes needed to its internal logic) ---
class TkinterLogHandler(logging.Handler):
    def __init__(self, text_widget_for_logging): # Changed parameter name for clarity
        super().__init__()
        self.text_widget = text_widget_for_logging # Assign the passed text widget
        self.queue = queue.Queue()

        # Define color tags in the text widget
        # These should use self.text_widget
        self.text_widget.tag_config("DEBUG", foreground="gray")
        self.text_widget.tag_config("INFO", foreground="black") 
        self.text_widget.tag_config("WARNING", foreground="#E69138")
        self.text_widget.tag_config("ERROR", foreground="red", font=("TkDefaultFont", 9, "bold"))
        self.text_widget.tag_config("CRITICAL", foreground="white", background="red", font=("TkDefaultFont", 9, "bold"))
        self.text_widget.tag_config("TIMESTAMP", foreground="#512E5F")

        # Start polling the queue
        self.text_widget.after(100, self.poll_log_queue)

    def emit(self, record: logging.LogRecord):
        self.queue.put(record)

    def poll_log_queue(self):
        try:
            while True:
                record = self.queue.get(block=False)
                timestamp_str = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
                log_message = record.getMessage()
                level_name_tag = record.levelname
                effective_tag = level_name_tag
                if level_name_tag not in self.text_widget.tag_names(): # Check if tag exists
                    effective_tag = "INFO" # Fallback
                    if not hasattr(self, '_warned_unknown_tags'): self._warned_unknown_tags = set()
                    if level_name_tag not in self._warned_unknown_tags:
                        logging.debug(f"GUI Log Handler: Unknown log level '{level_name_tag}', using INFO style.")
                        self._warned_unknown_tags.add(level_name_tag)
                
                self.text_widget.configure(state='normal')
                self.text_widget.insert(tk.END, f"{timestamp_str} - ", ("TIMESTAMP",))
                self.text_widget.insert(tk.END, f"{record.levelname}", (effective_tag,))
                self.text_widget.insert(tk.END, f" - {log_message}\n")
                self.text_widget.configure(state='disabled')
                self.text_widget.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.text_widget.after(100, self.poll_log_queue)


class PlaylistMakerGUI:
    def __init__(self, root_window: ttk.Window): # Expecting a ttkbootstrap.Window
        self.root = root_window
        self.root.title(f"Playlist Maker GUI v{pm_constants.SCRIPT_VERSION}")

        # --- Apply a ttk theme and default font ---
        self.style = ttk.Style()
        available_themes = self.style.theme_names()
        logging.debug(f"GUI: Available ttk themes: {available_themes}")
        preferred_themes = ['clam', 'alt', 'vista', 'xpnative', 'default'] # Order of preference
        for theme in preferred_themes:
            if theme in available_themes:
                try:
                    self.style.theme_use(theme)
                    logging.info(f"GUI: Applied ttk theme: {theme}")
                    break
                except tk.TclError:
                    logging.warning(f"GUI: Could not apply ttk theme '{theme}'.")
        else: # If no preferred theme worked
            logging.warning(f"GUI: None of the preferred themes worked. Using system default: {self.style.theme_use()}")
        
        # Set a default font for all ttk widgets (can be overridden by theme)
        # You might want to set this *after* theme_use or per widget type if theme overrides too much
        try:
            # default_font_family = "Segoe UI" if sys.platform == "win32" else "Calibri" if sys.platform == "win32" else "DejaVu Sans"
            # self.style.configure('.', font=(default_font_family, 9))
            #ttk.Style().configure("TLabel", padding=3, font=('Verdana', 9))
            #ttk.Style().configure("TButton", padding=5, font=('Verdana', 9))
            #ttk.Style().configure("TEntry", padding=3, font=('Verdana', 9))
            #ttk.Style().configure("TCheckbutton", padding=3, font=('Verdana', 9))
            #ttk.Style().configure("TRadiobutton", padding=3, font=('Verdana', 9))
            #ttk.Style().configure("TSpinbox", padding=3, font=('Verdana', 9))
            #ttk.Style().configure("TCombobox", padding=3, font=('Verdana', 9))

            # A more global approach (might be overridden by specific widget configurations below)
            base_font = font.nametofont("TkDefaultFont")
            base_font_family = base_font.actual()["family"] # Try to keep system default family
            # On some systems TkDefaultFont size is too small, so we adjust.
            # You can force a family like "Segoe UI", "Calibri", "DejaVu Sans", "Arial"
            # base_font.configure(family="Calibri", size=10)
            base_font.configure(size=10) # Just increase size of default font
            self.root.option_add("*Font", base_font)


        except Exception as e:
            logging.warning(f"GUI: Could not set default font style: {e}")


        main_frame = ttk.Frame(self.root, padding="10 10 10 10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Input Source Frame (File or AI) ---
        input_source_frame = ttk.LabelFrame(main_frame, text="Input Source", padding="10 10")
        input_source_frame.pack(fill=tk.X, pady=(0,10))
        
        self.input_mode_var = tk.StringVar(value="file")
        row_idx = 0
        
        # Radiobutton for File mode
        self.file_radio_btn = ttk.Radiobutton(input_source_frame, text="Playlist File:", 
                                              variable=self.input_mode_var, value="file", 
                                              command=self.toggle_input_mode)
        self.file_radio_btn.grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=5)
        
        self.playlist_file_entry = ttk.Entry(input_source_frame, width=50)
        self.playlist_file_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=5)
        self.playlist_file_browse_btn = ttk.Button(input_source_frame, text="Browse...", command=self.browse_playlist)
        self.playlist_file_browse_btn.grid(row=row_idx, column=2, padx=5, pady=5)
        
        row_idx += 1
        
        # Radiobutton for AI mode
        self.ai_radio_btn = ttk.Radiobutton(input_source_frame, text="AI Prompt:    ", 
                                            variable=self.input_mode_var, value="ai", 
                                            command=self.toggle_input_mode)
        # Adjust sticky for the label if the Text widget is taller
        self.ai_radio_btn.grid(row=row_idx, column=0, sticky=tk.NW, padx=5, pady=5) # sticky=tk.NW (North-West)
        
        # --- MODIFIED: AI Prompt Entry (use ScrolledText) ---
        self.ai_prompt_entry = scrolledtext.ScrolledText(
            input_source_frame, 
            width=50,  # Characters wide
            height=4,  # Number of lines high
            wrap=tk.WORD, 
            state=tk.DISABLED,
            relief=tk.SUNKEN, # Match log area relief for consistency
            borderwidth=1    # Match log area borderwidth
        )
        # Optional: Try to set a font similar to other entries if theme doesn't cover it
        # entry_font = ttk.Style().lookup("TEntry", "font") # Get default TEntry font
        # if entry_font:
        #    self.ai_prompt_entry.configure(font=entry_font)
        # else: # Fallback if TEntry font not found
        #    self.ai_prompt_entry.configure(font=("TkDefaultFont", 10))

        self.ai_prompt_entry.grid(row=row_idx, column=1, sticky=tk.NSEW, padx=5, pady=5, columnspan=2) # columnspan=2 to take browse button space
        # --- END MODIFICATION ---
        
        self.ai_prompt_entry.bind("<Button-1>", self.on_ai_prompt_click)
        
        # Make the row containing the ScrolledText expandable if desired
        input_source_frame.rowconfigure(row_idx, weight=1) 
        input_source_frame.columnconfigure(1, weight=1)

        # --- Paths Frame ---
        paths_frame = ttk.LabelFrame(main_frame, text="Paths", padding="10 10")
        paths_frame.pack(fill=tk.X, pady=(0,10))
        
        row_idx = 0
        ttk.Label(paths_frame, text="Music Library Path:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=5)
        self.library_path_entry = ttk.Entry(paths_frame, width=50)
        self.library_path_entry.insert(0, os.path.expanduser(pm_constants.DEFAULT_SCAN_LIBRARY))
        self.library_path_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=5)
        ttk.Button(paths_frame, text="Browse...", command=self.browse_library).grid(row=row_idx, column=2, padx=5, pady=5)

        #row_idx += 1
        #ttk.Label(paths_frame, text="MPD Music Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=5)
        #self.mpd_music_dir_entry = ttk.Entry(paths_frame, width=50)
        #self.mpd_music_dir_entry.insert(0, os.path.expanduser(pm_constants.DEFAULT_MPD_MUSIC_DIR_CONF))
        #self.mpd_music_dir_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=5)
        #ttk.Button(paths_frame, text="Browse...", command=lambda: self.browse_directory(self.mpd_music_dir_entry)).grid(row=row_idx, column=2, padx=5, pady=5)

        row_idx += 1
        ttk.Label(paths_frame, text="Output Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=5)
        self.output_dir_entry = ttk.Entry(paths_frame, width=50)
        self.output_dir_entry.insert(0, pm_constants.DEFAULT_OUTPUT_DIR)
        self.output_dir_entry.grid(row=row_idx, column=1, sticky=tk.EW, padx=5, pady=5)
        ttk.Button(paths_frame, text="Browse...", command=self.browse_output).grid(row=row_idx, column=2, padx=5, pady=5)
        paths_frame.columnconfigure(1, weight=1)


        # --- Options Frame ---
        options_frame = ttk.LabelFrame(main_frame, text="Options", padding="10 10")
        options_frame.pack(fill=tk.X, pady=(0,10))

        # Sub-frame for matching options
        matching_options_subframe = ttk.Frame(options_frame, padding="0 0 0 5")
        matching_options_subframe.pack(fill=tk.X)

        ttk.Label(matching_options_subframe, text="Match Threshold (0-100):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.threshold_var = tk.IntVar(value=pm_constants.DEFAULT_MATCH_THRESHOLD)
        self.threshold_spinbox = ttk.Spinbox(matching_options_subframe, from_=0, to=100, textvariable=self.threshold_var, width=7) # ttk.Spinbox often better
        self.threshold_spinbox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(matching_options_subframe, text="Live Penalty (0.0-1.0):").grid(row=0, column=2, sticky=tk.W, padx=(20,5), pady=5)
        self.live_penalty_var = tk.DoubleVar(value=pm_constants.DEFAULT_LIVE_PENALTY_FACTOR)
        self.live_penalty_spinbox = ttk.Spinbox(matching_options_subframe, from_=0.0, to=1.0, increment=0.05, format="%.2f", textvariable=self.live_penalty_var, width=7)
        self.live_penalty_spinbox.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Sub-frame for general boolean options
        general_options_subframe = ttk.Frame(options_frame, padding="0 5 0 5")
        general_options_subframe.pack(fill=tk.X)

        self.interactive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(general_options_subframe, text="Use Console Interactive Mode (CLI Prompts)", variable=self.interactive_var).grid(row=0, column=0, sticky=tk.W, columnspan=2, pady=5)
        
        self.force_rescan_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(general_options_subframe, text="Force Full Library Rescan (ignore cache)", variable=self.force_rescan_var).grid(row=0, column=2, sticky=tk.W, padx=(20,0), columnspan=2, pady=5)

        self.copy_to_mpd_var = tk.BooleanVar()
        self.mpd_copy_check = ttk.Checkbutton(general_options_subframe, text="Copy to MPD Playlist Dir:", variable=self.copy_to_mpd_var, command=self.toggle_mpd_path_entry)
        self.mpd_copy_check.grid(row=1, column=0, sticky=tk.W, pady=5)

        self.mpd_playlist_dir_entry = ttk.Entry(general_options_subframe, width=40, state=tk.DISABLED)
        self.mpd_playlist_dir_entry.insert(0, os.path.expanduser(pm_constants.DEFAULT_MPD_PLAYLIST_DIR_CONF))
        self.mpd_playlist_dir_entry.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=5)
        self.mpd_playlist_browse_button = ttk.Button(general_options_subframe, text="Browse...", command=lambda: self.browse_directory(self.mpd_playlist_dir_entry), state=tk.DISABLED)
        self.mpd_playlist_browse_button.grid(row=1, column=2, padx=5, pady=5)
        general_options_subframe.columnconfigure(1, weight=1)

        # Sub-frame for AI, Logging, Output Format
        adv_options_subframe = ttk.Frame(options_frame, padding="0 5 0 5")
        adv_options_subframe.pack(fill=tk.X)

        ttk.Label(adv_options_subframe, text="AI Model (optional):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.ai_model_entry = ttk.Entry(adv_options_subframe, width=25)
        self.ai_model_entry.insert(0, pm_constants.DEFAULT_AI_MODEL)
        self.ai_model_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        self.ai_model_entry.config(state=tk.DISABLED) # Initial state

        ttk.Label(adv_options_subframe, text="File Log Level:").grid(row=0, column=2, sticky=tk.W, padx=(20,5), pady=5)
        self.log_level_var = tk.StringVar(value="INFO")
        self.log_level_combo = ttk.Combobox(adv_options_subframe, textvariable=self.log_level_var,
                                            values=["DEBUG", "INFO", "WARNING", "ERROR"], state="readonly", width=12)
        self.log_level_combo.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)

        ttk.Label(adv_options_subframe, text="Output Filename Format:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.output_name_format_entry = ttk.Entry(adv_options_subframe, width=30)
        self.output_name_format_entry.insert(0, pm_constants.DEFAULT_OUTPUT_NAME_FORMAT) # Show default
        self.output_name_format_entry.grid(row=1, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5)
        adv_options_subframe.columnconfigure(1, weight=1) # Allow output format entry to expand slightly

        # --- Action Frame ---
        action_frame = ttk.Frame(main_frame, padding="0 10 0 0")
        action_frame.pack(fill=tk.X)
        self.generate_button = ttk.Button(action_frame, text="Generate Playlist", command=self.run_generate_playlist_thread, style="Accent.TButton") # Example of custom style
        # To define Accent.TButton style:
        # self.style.configure("Accent.TButton", font=('Segoe UI', 10, 'bold'), padding=10)
        # self.style.map("Accent.TButton", background=[('active', '#A9A9A9')]) # Darker gray when active
        self.generate_button.pack(pady=10) # Centered with some vertical padding

        # --- Log Output Frame ---
        log_frame = ttk.LabelFrame(main_frame, text="Log Output", padding="10 10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(5,0))
        self.log_text_area = scrolledtext.ScrolledText(log_frame, height=15, width=80, state='disabled', wrap=tk.WORD, relief=tk.SUNKEN, borderwidth=1)
        # self.log_text_area.configure(font=("Consolas", 9)) # Example of specific font for log
        self.log_text_area.pack(fill=tk.BOTH, expand=True)

        self.setup_gui_logging()
        self.toggle_input_mode()

    def on_ai_prompt_click(self, event):
        """Called when the user clicks on the AI prompt entry field."""
        # If AI mode is not already active, switch to it.
        if self.input_mode_var.get() != "ai":
            self.input_mode_var.set("ai") # Set the radio button variable
            self.toggle_input_mode()      # Call toggle to update states and focus
        
        # The toggle_input_mode will now set focus, but we can ensure it again
        # if the widget was already enabled but not focused (e.g., tabbing away and back).
        # However, the main goal here is the mode switch.
        # If the widget was disabled, toggle_input_mode enables it and sets focus.
        # If it was already enabled (AI mode already active), this click just naturally focuses it.
        # No need for an explicit focus_set here if toggle_input_mode handles it.
        return # Important for some Tkinter event bindings to allow default 

    def toggle_input_mode(self):
        mode = self.input_mode_var.get()
        is_ai_mode = (mode == "ai")
        
        # Enable/disable Playlist File entry and its browse button
        self.playlist_file_entry.config(state=tk.NORMAL if not is_ai_mode else tk.DISABLED)
        self.playlist_file_browse_btn.config(state=tk.NORMAL if not is_ai_mode else tk.DISABLED)
        
        # Enable/disable AI Prompt entry and AI Model entry
        self.ai_prompt_entry.config(state=tk.NORMAL if is_ai_mode else tk.DISABLED)
        # Ensure self.ai_model_entry is defined before this line is reached
        if hasattr(self, 'ai_model_entry'): # Check if it exists, good for during dev
            self.ai_model_entry.config(state=tk.NORMAL if is_ai_mode else tk.DISABLED)
        else:
            logging.warning("GUI: ai_model_entry widget not found during toggle_input_mode.")

        # Set focus
        if is_ai_mode:
            self.ai_prompt_entry.after(0, self.ai_prompt_entry.focus_set)
        else: # "file" mode
            self.playlist_file_entry.after(0, self.playlist_file_entry.focus_set)

    def toggle_mpd_path_entry(self):
        is_enabled = self.copy_to_mpd_var.get()
        new_state = tk.NORMAL if is_enabled else tk.DISABLED
        self.mpd_playlist_dir_entry.config(state=new_state)
        self.mpd_playlist_browse_button.config(state=new_state)

    def setup_gui_logging(self):
        gui_log_handler = TkinterLogHandler(self.log_text_area)
        gui_log_handler.setLevel(logging.DEBUG)
        root_logger = logging.getLogger() # Get the root logger
        
        # Remove any old instance of TkinterLogHandler to prevent duplicates if method is called again
        for handler in list(root_logger.handlers): # Iterate over a copy
            if isinstance(handler, TkinterLogHandler):
                root_logger.removeHandler(handler)
        root_logger.addHandler(gui_log_handler)
        
        # Ensure root logger passes messages of appropriate level
        # If root logger's level is higher than DEBUG, DEBUG messages won't reach the handler
        if root_logger.level == 0 or root_logger.level > logging.DEBUG: # 0 is NOTSET
             root_logger.setLevel(logging.DEBUG)
        logging.info("GUI Log Handler initialized and attached to root logger.")


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

    def browse_library(self): self.browse_directory(self.library_path_entry)
    def browse_output(self): self.browse_directory(self.output_dir_entry)

    def run_generate_playlist_thread(self):
        input_mode = self.input_mode_var.get()
        base_argv = [] # Arguments defining the input source (file or AI)

        if input_mode == "file":
            playlist_file = self.playlist_file_entry.get().strip()
            if not playlist_file:
                messagebox.showerror("Input Error", "Please select a playlist file.")
                return
            base_argv.append(playlist_file)
        elif input_mode == "ai":
            # --- MODIFIED: Get text from ScrolledText ---
            # .get("1.0", tk.END) gets all text from beginning to end
            # The -1c removes the automatic newline ScrolledText/Text adds at the end.
            ai_prompt = self.ai_prompt_entry.get("1.0", tk.END+"-1c").strip() 
            # --- END MODIFICATION ---
            if not ai_prompt:
                messagebox.showerror("InputError", "Please enter an AI prompt.")
                return
            base_argv.extend(["--ai-prompt", ai_prompt])
        else:
            messagebox.showerror("Input Error", "Invalid input mode selected.")
            return

        self.log_text_area.configure(state='normal')
        self.log_text_area.delete('1.0', tk.END)
        self.log_text_area.configure(state='disabled')
        logging.info("GUI: Starting playlist generation...")
        if self.interactive_var.get():
            logging.warning("GUI: CONSOLE INTERACTIVE MODE is enabled. Prompts will appear in the terminal.")

        self.generate_button.config(text="Generating...", state=tk.DISABLED)
        
        thread = threading.Thread(target=self.execute_playlist_maker, args=(base_argv,), daemon=True)
        thread.start()

    def execute_playlist_maker(self, base_argv):
        try:
            argv = list(base_argv) # Start with input source args

            # Append path options
            for arg_name, entry_widget in [
                ("--library", self.library_path_entry),
                #("--mpd-music-dir", self.mpd_music_dir_entry),
                ("--output-dir", self.output_dir_entry)
            ]:
                path_val = entry_widget.get().strip()
                if path_val: argv.extend([arg_name, path_val])

            argv.extend(["--threshold", str(self.threshold_var.get())])
            argv.extend(["--live-penalty", f"{self.live_penalty_var.get():.2f}"])

            if self.interactive_var.get(): argv.append("--interactive")
            if self.force_rescan_var.get(): argv.append("--force-rescan")

            if self.copy_to_mpd_var.get():
                mpd_playlist_path = self.mpd_playlist_dir_entry.get().strip()
                if mpd_playlist_path: argv.extend(["--mpd-playlist-dir", mpd_playlist_path])
                else: argv.append("--mpd-playlist-dir") # Use default/config

            log_level = self.log_level_var.get()
            if log_level and log_level != "INFO": # Only add if not the default
                argv.extend(["--log-level", log_level])
            
            output_name_format_val = self.output_name_format_entry.get().strip()
            if output_name_format_val and output_name_format_val != pm_constants.DEFAULT_OUTPUT_NAME_FORMAT:
                argv.extend(["--output-name-format", output_name_format_val])

            logging.info(f"GUI: Running backend with args: {argv}")
            result = pm_main_cli(argv_list=argv)

            if result and result.get("success"):
                logging.info("GUI: Playlist generation process completed successfully!")
                skipped_tracks = result.get("skipped_tracks", [])
                message = "Playlist generated successfully!"
                if skipped_tracks:
                    logging.warning("\n--- Skipped/Missing Tracks ---")
                    for item in skipped_tracks: logging.warning(f"  - {item}")
                    logging.warning(f"Total skipped/missing: {len(skipped_tracks)}. See missing-tracks.txt if saved.")
                    message += f"\n({len(skipped_tracks)} tracks skipped/missing)"
                else:
                    logging.info("GUI: All tracks from input were matched and included!")
                self.root.after(0, lambda msg=message: messagebox.showinfo("Success", msg))

            elif result and result.get("error"):
                error_msg = result.get("error", "Unknown error from playlist maker.")
                logging.error(f"GUI: Playlist maker reported an error: {error_msg}")
                self.root.after(0, lambda err_val=error_msg: messagebox.showerror("Playlist Maker Error", err_val))
            else:
                logging.critical("GUI: Received unexpected or no result from playlist maker process.")
                self.root.after(0, lambda: messagebox.showerror("Process Error", "Playlist maker did not return a clear status."))

        except Exception as e:
            logging.error(f"GUI: Unexpected error during playlist generation thread: {e}", exc_info=True)
            self.root.after(0, lambda err_val=str(e): messagebox.showerror("Generation Error", f"An unexpected error occurred:\n{err_val}"))
        finally:
            self.root.after(0, lambda: self.generate_button.config(text="Generate Playlist", state=tk.NORMAL))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s (%(name)s:%(funcName)s) - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)] 
    )
    logging.info("GUI_MAIN (__main__): Initializing PlaylistMakerGUI application...")

    root = tk.Tk()
    app = PlaylistMakerGUI(root)

    logging.info("GUI_MAIN (__main__): Starting Tkinter main loop.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logging.info("GUI_MAIN (__main__): KeyboardInterrupt received, GUI shutting down.")
        print("\nPlaylist Maker GUI closed via Ctrl+C.")
    finally:
        logging.info("GUI_MAIN (__main__): Tkinter main loop finished or interrupted.")