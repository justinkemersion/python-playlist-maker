# Playlist Maker for MPD

This Python script converts simple text files containing `Artist - Track` listings into `.m3u` playlists suitable for the Music Player Daemon (MPD). It intelligently matches the tracks against your local music library using fuzzy string matching and metadata analysis.

## Overview

The script scans your specified music library, builds an index of your tracks (including metadata like artist, title, album, duration, and identifying live recordings), and then processes an input text file. For each `Artist - Track` line in the input file, it searches the library index for the best match. It generates an M3U playlist file with relative paths based on your MPD music directory configuration, making it directly usable by MPD. It also features an interactive mode for resolving ambiguities.

## Features

*   **Text List Input:** Reads simple `.txt` files with one `Artist - Track` per line.
*   **Library Scanning:** Scans your music library directory for supported audio files (`.mp3`, `.flac`, `.ogg`, `.m4a` by default).
*   **Metadata Extraction:** Uses `mutagen` to read artist, title, album, and duration tags.
*   **Fuzzy Matching:** Uses `fuzzywuzzy` to find matches even with slight variations in names or typos.
*   **Smart Normalization:** Cleans up artist/track names before matching (handles case, accents, `&`/`/`/`and`, featuring artists like `(feat. ...)` , strips common parenthetical terms like `(remix)`, removes track numbers).
*   **Live Track Handling:**
    *   Detects live tracks based on `(live)` in title/filename or keywords in album titles (e.g., "Live at", "Unplugged").
    *   Applies a configurable score penalty when matching a non-live input track to a live library track.
    *   Prioritizes live/studio tracks based on whether the input track specified `(live)`.
*   **MPD Compatibility:** Generates M3U playlists with paths relative to your configured MPD music directory.
*   **Interactive Mode (`-i`):** Prompts the user to resolve ambiguities when:
    *   Multiple good matches are found.
    *   No match meets the threshold.
    *   Offers choices like selecting a specific match, skipping the track, or picking a random track by the same artist.
*   **Missing Tracks Report:** Creates a separate text file listing tracks from the input that couldn't be matched or were skipped.
*   **Configurable:** Many options controllable via command-line arguments (paths, threshold, extensions, keywords, etc.).
*   **Logging:** Detailed logging to a file (`warning.log` by default) for troubleshooting.

## Prerequisites

*   **Python:** Version 3.7 or higher recommended.
*   **Pip:** Python's package installer (usually comes with Python).
*   **Python Libraries:**
    *   `mutagen`: For reading audio metadata.
    *   `fuzzywuzzy`: For fuzzy string matching.
    *   `python-levenshtein`: Improves `fuzzywuzzy` speed significantly (recommended, sometimes required by fuzzywuzzy).
    *   `pandas` (Optional): Used for a more robust check of track duration values (like NaN). If not installed, the script uses a basic fallback check.

## Installation

1.  Ensure Python 3.7+ and pip are installed (see detailed setup guide below if needed).
2.  Place the `playlist-maker.py` script in your desired project directory.
3.  Create a `requirements.txt` file (see guide below) in the same directory.
4.  Create and activate a Python virtual environment within the project directory (recommended).
5.  Install the required libraries: `pip install -r requirements.txt`

*(See the detailed "Python Environment Setup Walkthrough" section below if you need help with these steps).*

## Usage

The script is run from the command line.

**Basic Example:**

```bash
python playlist-maker.py input_playlist.txt

usage: playlist-maker.py [-h] [-l LIBRARY] [--mpd-music-dir MPD_MUSIC_DIR]
                         [-o OUTPUT_DIR] [--missing-dir MISSING_DIR]
                         [-m [MPD_PLAYLIST_DIR]] [-t [0-100]]
                         [--live-penalty [0.0-1.0]] [--log-file LOG_FILE]
                         [--log-mode {append,overwrite}]
                         [--log-level {DEBUG,INFO,WARNING,ERROR}]
                         [-e EXTENSIONS [EXTENSIONS ...]]
                         [--live-album-keywords LIVE_ALBUM_KEYWORDS [LIVE_ALBUM_KEYWORDS ...]]
                         [--strip-keywords STRIP_KEYWORDS [STRIP_KEYWORDS ...]] [-i]
                         playlist_file

Generate M3U playlists by matching 'Artist - Track' lines against a music library.

positional arguments:
  playlist_file         Input text file (one 'Artist - Track' per line).

options:
  -h, --help            show this help message and exit
  -l LIBRARY, --library LIBRARY
                        Music library path to scan. (default: ~/music)
  --mpd-music-dir MPD_MUSIC_DIR
                        MPD 'music_directory' path (for relative paths in M3U). Must
                        match mpd.conf. (default: ~/music)
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Output directory for generated M3U playlists. (default:
                        ./playlists)
  --missing-dir MISSING_DIR
                        Directory to save lists of tracks that were not found or
                        skipped. (default: ./missing-tracks)
  -m [MPD_PLAYLIST_DIR], --mpd-playlist-dir [MPD_PLAYLIST_DIR]
                        Optionally copy the generated M3U to MPD's
                        'playlist_directory'. If flag is present without a value,
                        uses the default path. Provide a path to override the
                        default. (default: ~/.config/mpd/playlists)
  -t [0-100], --threshold [0-100]
                        Minimum fuzzy match score [0-100] required for
                        title/filename match. (default: 75)
  --live-penalty [0.0-1.0]
                        Score multiplier (penalty) for library tracks marked as 'live'
                        when the input track is not. Lower value = higher penalty
                        (e.g., 0.75 means score * 0.75). (default: 0.75)
  --log-file LOG_FILE   Path for the log file. (default: <script_dir>/warning.log)
  --log-mode {append,overwrite}
                        Log file mode ('append' or 'overwrite'). (default:
                        overwrite)
  --log-level {DEBUG,INFO,WARNING,ERROR}
                        Set the logging level for the file log. (default: INFO)
  -e EXTENSIONS [EXTENSIONS ...], --extensions EXTENSIONS [EXTENSIONS ...]
                        Space-separated list of supported audio file extensions (e.g.,
                        .mp3 .flac). (default: ['.mp3', '.flac', '.ogg', '.m4a'])
  --live-album-keywords LIVE_ALBUM_KEYWORDS [LIVE_ALBUM_KEYWORDS ...]
                        Space-separated list of regex patterns (case-insensitive) to
                        identify live albums by title. (default: ['\\blive\\b',
                        '\\bunplugged\\b', '\\bconcert\\b', 'live at', 'live in',
                        'live from', 'official bootleg', 'acoustic sessions',
                        'peel session[s]?', 'radio session[s]?', 'mtv unplugged'])
  --strip-keywords STRIP_KEYWORDS [STRIP_KEYWORDS ...]
                        Space-separated list of keywords (case-insensitive, treated
                        as regex word boundaries) to strip from within parentheses
                        during normalization (e.g., remix edit version). (default:
                        ['remix', 'radio edit', 'edit', 'version', 'mix',
                        'acoustic', 'mono', 'stereo', 'reprise', 'instrumental'])
  -i, --interactive     Enable interactive mode to resolve ambiguous matches, handle
                        missing tracks, or confirm substitutions (like live/studio).
                        (default: False)
```

## 2. Python Environment Setup Walkthrough

Here's a guide to setting up the necessary Python environment to run the script.

**Goal:** Install Python (if needed), install the required packages (`mutagen`, `fuzzywuzzy`, `python-levenshtein`) into an isolated virtual environment, and run the script.

**Steps:**

1.  **Check for Python Installation:**
    *   Open your terminal or command prompt.
    *   Type `python --version` and press Enter.
    *   If you see `Python 3.x.y` (where x is ideally 7 or higher), you likely have Python 3 installed. You might need to try `python3 --version` on macOS or Linux.
    *   If you get an error or see Python 2.x.y, you need to install Python 3.

2.  **Install Python 3 (If Needed):**
    *   **Windows:**
        *   Go to the official Python website: [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/)
        *   Download the latest stable Python 3 installer.
        *   Run the installer. **Crucially, make sure to check the box that says "Add Python 3.x to PATH"** during installation. This makes it easier to run Python from the command prompt.
        *   Verify by opening a *new* command prompt and running `python --version`.
    *   **macOS:**
        *   Python 3 might already be installed. Try `python3 --version`.
        *   If not, download the installer from [https://www.python.org/downloads/macos/](https://www.python.org/downloads/macos/). Run it.
        *   Alternatively, if you use Homebrew: `brew install python3`.
        *   Verify in a *new* terminal window with `python3 --version`.
    *   **Linux (Debian/Ubuntu/Mint):**
        *   Python 3 is usually pre-installed. Verify with `python3 --version`.
        *   If not, or if you need a newer version: `sudo apt update && sudo apt install python3 python3-pip python3-venv`
    *   **Linux (Fedora/CentOS/RHEL):**
        *   Verify with `python3 --version`.
        *   If not: `sudo dnf install python3 python3-pip`

3.  **Check/Ensure Pip:**
    *   Pip is Python's package installer and usually comes with Python 3.4+.
    *   Check its version: `pip --version` or `pip3 --version`.
    *   It's good practice to upgrade pip:
        ```bash
        python -m pip install --upgrade pip
        # Or maybe: python3 -m pip install --upgrade pip
        ```

4.  **Navigate to Your Project Directory:**
    *   Open your terminal/command prompt.
    *   Use the `cd` (change directory) command to go to the folder where you saved `playlist-maker.py`.
        ```bash
        cd path/to/your/playlist-maker-folder
        ```

5.  **Create `requirements.txt` file:**
    *   In your project directory, create a new text file named `requirements.txt`.
    *   Add the following lines to this file:

        ```txt
        mutagen
        fuzzywuzzy
        python-levenshtein
        # pandas # Optional: uncomment if you want to install pandas for better duration checks
        ```
    *   *Why `python-levenshtein`?* `fuzzywuzzy` uses it to calculate string similarity much faster. Without it, `fuzzywuzzy` will be slower and might show a warning.

6.  **Create a Virtual Environment:**
    *   This creates an isolated space for your project's dependencies, preventing conflicts with other Python projects.
    *   In your terminal (while in the project directory), run:
        ```bash
        python -m venv venv
        # Or on some systems: python3 -m venv venv
        ```
    *   This creates a folder named `venv` in your project directory.

7.  **Activate the Virtual Environment:**
    *   You need to activate the environment *each time* you work on the project in a new terminal session.
    *   **Windows (Command Prompt):**
        ```cmd
        venv\Scripts\activate.bat
        ```
    *   **Windows (PowerShell):**
        ```powershell
        venv\Scripts\Activate.ps1
        # If you get an error about execution policy, you might need to run:
        # Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
        # and then try activating again.
        ```
    *   **macOS / Linux (bash/zsh):**
        ```bash
        source venv/bin/activate
        ```
    *   **How to tell it's active:** Your terminal prompt will usually change to show `(venv)` at the beginning, like `(venv) C:\path\to\project>` or `(venv) user@machine:~/path/to/project$`.

8.  **Install the Requirements:**
    *   While the virtual environment is active (you see `(venv)` in the prompt), run:
        ```bash
        pip install -r requirements.txt
        ```
    *   This will download and install `mutagen`, `fuzzywuzzy`, and `python-levenshtein` (and `pandas` if you uncommented it) *into* the `venv` folder.

9.  **Run the Script:**
    *   Now you can run the playlist maker script:
        ```bash
        python playlist-maker.py your_input_file.txt [other options...]
        # Or possibly: python3 playlist-maker.py ...
        # Use the -i or --interactive to interact with the playlist-maker.py to help solve issues.
        ```

10. **Deactivate the Virtual Environment (When Done):**
    *   When you're finished working on the project in this terminal session, simply type:
        ```bash
        deactivate
        ```
    *   Your prompt should return to normal.

You now have a dedicated, isolated environment for the playlist maker! The next time you want to run it, just `cd` to the directory and activate the venv again (`source venv/bin/activate` or `venv\Scripts\activate.bat`).

---