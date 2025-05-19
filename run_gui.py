#!/usr/bin/env python3
import ttkbootstrap as ttk # Import ttkbootstrap as ttk
from ttkbootstrap.constants import * # Often useful
import logging
import sys
# Ensure playlist_maker_gui can be found (if it's in the same directory)
# If playlist_maker_gui.py is also at the root, this direct import is fine.
from playlist_maker.ui.gui import PlaylistMakerGUI

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s (%(name)s) - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)] 
    )

    logging.info("RUN_GUI: Initializing PlaylistMakerGUI application with ttkbootstrap...")

    # --- Create a themed window from ttkbootstrap ---
    # List of themes: litera, cosmo, flatly, journal, lumen, minty, pulse, sandstone,
    # united, yeti, cyborg, darkly, solar, superhero (dark themes)
    # See ttkbootstrap docs for more.
    try:
        root = ttk.Window(themename="cyborg") 
    except Exception as e:
        logging.error(f"RUN_GUI: Failed to initialize ttkbootstrap: {e}. Falling back.")
        root = tk.Tk() # Use the imported tk for fallback
        messagebox.showwarning("Theming Error", "Could not apply custom theme. Using default look.") # Now messagebox is defined


    root.title("Playlist Maker GUI") # You can set title here or in PlaylistMakerGUI
    # You can also set minsize, initial geometry etc. on the root window
    # root.geometry("800x600") 

    app = PlaylistMakerGUI(root) # Pass the themed window to your GUI class

    logging.info("RUN_GUI: Starting Tkinter main loop.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logging.info("RUN_GUI: KeyboardInterrupt received, GUI shutting down.")
        print("\nPlaylist Maker GUI closed via Ctrl+C.")
    finally:
        logging.info("RUN_GUI: Tkinter main loop finished or interrupted.")