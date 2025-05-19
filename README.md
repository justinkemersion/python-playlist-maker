# Playlist Maker (.m3u)

This Python application intelligently converts user inputs—either from AI-generated prompts (via OpenAI) or local text files listing `Artist - Track`—into `.m3u` playlists. It matches these inputs against your local music library using advanced string matching and metadata analysis, creating playlists compatible with a wide range of music players.

## Concept

The core idea is to streamline playlist creation for your personal music library. Whether you prefer crafting lists by hand, leveraging AI for inspiration, or a mix of both, Playlist Maker helps you quickly turn those ideas into playable `.m3u` files. This version enhances the process with AI-driven playlist drafting and a persistent library cache for faster operation.

## Overview

Playlist Maker scans your music library, building a smart index of your tracks (including artist, title, album, duration, live recording status, and file modification times). This index is then cached in an SQLite database for significantly faster startups on subsequent runs.

When you provide an input (an AI prompt or a text file):
1.  If using an AI prompt, the application queries OpenAI (GPT models) to generate a list of `Artist - Song` suggestions. You can preview and accept/reject this list.
2.  The accepted track list (from AI or file) is then processed. Each entry is fuzzi-matched against your cached library index.
3.  An M3U playlist is generated with relative paths (based on your MPD music directory configuration), ready for use in various music players.
4.  An interactive mode helps resolve ambiguities, and a report lists any tracks that couldn't be matched.

Here's an example of using an AI prompt with the simple GUI:

```bash
python run_gui.py

# Or simply: python run_cli.py --ai-prompt "Chill electronic music for late night coding" -i (for cli mode)
```
![Library Scan Output](assets/playlist-maker-gui-example.png)

When an ambiguous match occurs in interactive mode, you'll see a prompt like this:

![Interactive Prompt Example 1](assets/playlist-maker-interactive-mode-version-choice.png)

Here is another example of the interactive mode showing a prompt for a track selection:

![Interactive Prompt Example 2](assets/playlist-maker-interactive-mode-alternative-track-selection.png)

Another example highlighting a number of live options to choose from:

![Interactive Prompt Example 3](assets/playlist-maker-interactive-mode-many-live-options-example.png)

And finally, when the playlist is ready:

![Playlist Output Finished](assets/playlist-maker-completed.png)


## Features

- **AI-Powered Playlist Generation (New!):**
    - Optionally generate an initial "Artist - Track" list using an AI prompt (e.g., via OpenAI's GPT models).
    - Requires configuration of an API key (OpenAI).
    - Allows user to preview and confirm the AI-generated list before processing.
    - Generated list is then matched against your local library like a text file input.
- **Text List Input:** Reads simple `.txt` files with one `Artist - Track` per line.
- **Library Scanning:** Scans your music library directory for supported audio files (`.mp3`, `.flac`, `.ogg`, `.m4a` by default).
- **Metadata Extraction:** Uses `mutagen` to read artist, title, album, and duration tags.
- **Fuzzy Matching:** Uses `fuzzywuzzy` to find matches even with slight variations in names or typos.
- **Smart Normalization:** Cleans up artist/track names before matching (handles case, accents, `&`/`/`/`and`, featuring artists like `(feat. ...)` , strips common parenthetical terms like `(remix)`, removes track numbers).
- **Live Track Handling:**
    - Detects live tracks based on `(live)` in title/filename or keywords in album titles (e.g., "Live at", "Unplugged").
    - Applies a configurable score penalty when matching a non-live input track to a live library track.
    - Prioritizes live/studio tracks based on whether the input track specified `(live)`.
- **Customizable Output Filenames:** Allows users to define a format string for the generated M3U playlist filename using placeholders for basename, date/time components, and transformations (e.g., capitalization, separator changes).
- **MPD Compatibility:** Generates M3U playlists with paths relative to your configured MPD music directory.
- **Interactive Mode (`-i`):** Prompts the user to resolve ambiguities when:
    - Multiple good matches are found.
    - No match meets the threshold.
    - Offers choices like selecting a specific match, skipping the track, or picking a random track by the same artist.
- **Missing Tracks Report:** Creates a separate text file listing tracks from the input that couldn't be matched or were skipped.
- **Persistent Library Cache (New!):**
    - After the initial full scan, the script caches your library index (track metadata, paths, modification times) in an SQLite database (`data/library_index.sqlite` by default).
    - Subsequent runs load from this cache, only scanning for new, modified, or deleted files, leading to significantly faster startup times for large libraries.
    - Use `--force-rescan` to ignore the cache and rebuild the index from scratch.
    - Configurable via the `[Cache]` section in `playlist_maker.conf`.
- **Configurable:** Many options controllable via configuration files (`playlist_maker.conf`, `~/.config/playlist-maker/config.ini`) and command-line arguments.
- **Logging:** Detailed logging to a file (`warning.log` by default) for troubleshooting.

## Prerequisites

- **Python:** Version 3.7 or higher recommended.
- **Pip:** Python's package installer (usually comes with Python).
- **Python Libraries:**
    - `mutagen`
    - `fuzzywuzzy`
    - `python-levenshtein` (Recommended for `fuzzywuzzy` performance)
    - `openai` (For AI playlist generation)
    - `pandas` (Optional, for enhanced duration checks; script has a fallback)

## Installation

1.  **Clone or Download:** Clone this repository or download the project files.
2.  **Python Environment Setup:** Follow the "Detailed Python Environment Setup Walkthrough" below to install Python (if needed) and set up a virtual environment.
3.  **Create `requirements.txt`:** In your project directory, create a file named `requirements.txt` with the following content:

    ```txt
    mutagen
    fuzzywuzzy
    python-levenshtein
    openai>=1.3.0  # Specify a version or a minimum version for openai
    # pandas # Optional: uncomment if you want to install pandas
    ```

4.  **Install Dependencies:** Activate your virtual environment and run:
    ```bash
    pip install -r requirements.txt
    ```

---

### Detailed Python Environment Setup Walkthrough

1.  **Check for Python Installation:**

    - Open your terminal/command prompt.
    - Type `python --version` (or `python3 --version`) and press Enter.
    - If you see `Python 3.x.y` (where x >= 7), you're good.
    - If not, or if you see Python 2, you need to install/upgrade Python 3.

2.  **Install Python 3 (If Needed):**

    - **Windows:** Download from [python.org/downloads/windows/](https://www.python.org/downloads/windows/). **Crucially, check "Add Python 3.x to PATH"** during installation.
    - **macOS:** Download from [python.org/downloads/macos/](https://www.python.org/downloads/macos/) or use Homebrew (`brew install python3`).
    - **Linux (Debian/Ubuntu):** `sudo apt update && sudo apt install python3 python3-pip python3-venv`
    - **Linux (Fedora/CentOS):** `sudo dnf install python3 python3-pip`
    - Verify with `python3 --version` in a _new_ terminal window.

3.  **Ensure Pip is Up-to-Date:**

    ```bash
    python3 -m pip install --upgrade pip
    ```

4.  **Navigate to Your Project Directory:**

    ```bash
    cd path/to/your/playlist-maker-folder
    ```

5.  **Create a Virtual Environment:**
    (The `requirements.txt` file should already be created in this directory from Step 3 of the main Installation section.)

    ```bash
    python3 -m venv venv
    ```

    This creates an isolated `venv` folder for project dependencies.

6.  **Activate the Virtual Environment:**

    - **Windows (Command Prompt):** `venv\Scripts\activate.bat`
    - **Windows (PowerShell):** `venv\Scripts\Activate.ps1` (You might need to adjust script execution policy: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process`)
    - **macOS / Linux (bash/zsh):** `source venv/bin/activate`
    - Your terminal prompt should now indicate the active environment (e.g., `(venv)`).

7.  **Install Requirements (If not done in main installation steps):**
    While the virtual environment is active:

    ```bash
    pip install -r requirements.txt
    ```

8.  **Running the Script:**
    With the virtual environment active:

    ```bash
    python run_cli.py your_input_file.txt [other options...]
    # Or, from the project root:
    python -m playlist_maker.app your_input_file.txt [other options...]
    ```

9.  **Deactivate (When Done):**
    ```bash
    deactivate
    ```

---

## Usage

The script is run from the command line. Here's a basic example and the help output:

**Basic Invocation:**

```bash
# Using a text file
python run_cli.py input_playlist.txt

# Using an AI prompt
python run_cli.py --ai-prompt "Acoustic songs for a rainy afternoon"

# AI prompt with specific model and interactive mode
python run_cli.py -i --ai-prompt "Obscure 70s psych rock" --ai-model gpt-4-turbo-preview
```

**Help Output:**

```bash
python run_cli.py --help


usage: run_cli.py [-h] [--ai-prompt AI_PROMPT] [--ai-model AI_MODEL] [-l LIBRARY] [--mpd-music-dir MPD_MUSIC_DIR] [-o OUTPUT_DIR] [--missing-dir MISSING_DIR]
                  [-m [MPD_PLAYLIST_DIR]] [-t [0-100]] [--live-penalty [0.0-1.0]] [--output-name-format OUTPUT_NAME_FORMAT] [--log-file LOG_FILE]
                  [--log-mode {append,overwrite}] [--log-level {DEBUG,INFO,WARNING,ERROR}] [-e EXTENSIONS [EXTENSIONS ...]]
                  [--live-album-keywords LIVE_ALBUM_KEYWORDS [LIVE_ALBUM_KEYWORDS ...]] [--strip-keywords STRIP_KEYWORDS [STRIP_KEYWORDS ...]] [-i] [-v]
                  [playlist_file]

Generate M3U playlists by matching 'Artist - Track' lines against a music library.

positional arguments:
  playlist_file         Input text file (one 'Artist - Track' per line). Used if --ai-prompt is not. (default: None)

options:
  -h, --help            show this help message and exit
  --ai-prompt AI_PROMPT
                        Generate initial playlist using an AI prompt (e.g., 'Make me a sad indie folk playlist'). This generates an 'Artist - Song' list that then gets
                        processed. Overrides playlist_file. (default: None)
  -l, --library LIBRARY
                        Music library path. Cfg: Paths.library, Def: ~/music (default: None)
  --mpd-music-dir MPD_MUSIC_DIR
                        MPD music_directory path. Cfg: Paths.mpd_music_dir, Def: ~/music (default: None)
  -o, --output-dir OUTPUT_DIR
                        Output dir for M3U. Cfg: Paths.output_dir, Def: ./playlists (default: None)
  --missing-dir MISSING_DIR
                        Dir for missing tracks list. Cfg: Paths.missing_dir, Def: ./missing-tracks (default: None)
  -m, --mpd-playlist-dir [MPD_PLAYLIST_DIR]
                        Copy M3U to MPD dir. No value=use default/config. Cfg: Paths.mpd_playlist_dir (default: None)
  -t, --threshold [0-100]
                        Min match score [0-100]. Cfg: Matching.threshold, Def: 75 (default: None)
  --live-penalty [0.0-1.0]
                        Penalty for unwanted live match. Cfg: Matching.live_penalty, Def: 0.75 (default: None)
  --output-name-format OUTPUT_NAME_FORMAT
                        Custom format string for the output M3U filename. Placeholders: {basename}, {basename:transforms}, {YYYY}, {YY}, {MM}, {DD}, {hh}, {mm}, {ss}.
                        Transforms for basename (e.g., {basename:cp}): 'c'-capitalize words, 'u'-uppercase, 'l'-lowercase; 'p'-prettify spaces, 's'-hyphenate,
                        '_'-underscorify. Example: "{basename:cp}_{YYYY}-{MM}-{DD}.m3u" (Configurable, PyDef: {basename:cp}_{YYYY}-{MM}-{DD}.m3u) (default: None)
  --log-file LOG_FILE   Log file path. Cfg: Logging.log_file, Def: <project_root>/warning.log (default: None)
  --log-mode {append,overwrite}
                        Log file mode. Cfg: Logging.log_mode, Def: overwrite (default: None)
  --log-level {DEBUG,INFO,WARNING,ERROR}
                        Log level for file. Cfg: Logging.log_level, Def: INFO (default: None)
  -e, --extensions EXTENSIONS [EXTENSIONS ...]
                        Audio extensions. Cfg: General.extensions, Def: .mp3 .flac .ogg .m4a (default: None)
  --live-album-keywords LIVE_ALBUM_KEYWORDS [LIVE_ALBUM_KEYWORDS ...]
                        Regex patterns for live albums. Cfg: Matching.live_album_keywords (default: None)
  --strip-keywords STRIP_KEYWORDS [STRIP_KEYWORDS ...]
                        Keywords to strip from (). Cfg: Matching.strip_keywords (default: None)
  -i, --interactive     Enable interactive mode. Cfg: General.interactive, Def: false (default: None)
  -v, --version         Show program's version number and exit.

AI Playlist Generation Options (used with --ai-prompt):
  --ai-model AI_MODEL   Specify the AI model to use (e.g., gpt-4-turbo-preview). Cfg: AI.model, PyDef: gpt-3.5-turbo (default: None)
```

**Configuration Files**

The script can also be configured via two INI-style configuration files:

```
playlist_maker.conf: Place this file in the project root directory (alongside `run_cli.py`).

~/.config/playlist-maker/config.ini: User-specific configuration. (Assuming `CONFIG_FILENAME_USER = "config.ini"`)
```

Settings in these files are overridden by command-line arguments. Refer to the comments within playlist*maker.py (near the DEFAULT* constants) or the script's help output for available options and their sections (e.g., [Paths], [Matching], [Logging], [General]).

Example playlist_maker.conf structure:

```ini
[Paths]
library = ~/Music/my-library
mpd_music_dir = ~/Music/my-library
output_dir = ./generated-playlists
# mpd_playlist_dir = ~/.mpd/playlists

[Matching]
threshold = 80
live_penalty = 0.7

[Logging]
log_level = DEBUG

[General]
interactive = true
extensions = .mp3 .flac .opus .m4a .ogg

# Enable interactive mode by default? true/false, yes/no, 1/0.
interactive = false

[AI]
# Your OpenAI API key. Can be set here or via OPENAI_API_KEY environment variable.
# If left blank and OPENAI_API_KEY is not set, AI features will be disabled when an AI prompt is used.
api_key = YOUR_OPENAI_API_KEY_GOES_HERE

# Default AI model to use if --ai-model is not specified on the command line.
# Examples: gpt-3.5-turbo, gpt-4-turbo-preview, gpt-4
model = gpt-3.5-turbo

[Cache]
# Enable the persistent library index cache for faster startup on subsequent runs.
# If disabled, the library will be fully scanned each time.
enable_library_cache = true

# Filename for the SQLite database used for the library index cache.
# This will be stored in a 'data' subdirectory of your project.
# Default: library_index.sqlite
index_db_filename = library_index.sqlite
```

## Playlist Maker GUI

The GUI version can be run from the command line similarly with the `playlist_maker_gui.py` file. It's a more user-friendly interface for generating M3U playlists.

```bash
python playlist_maker_gui.py -i --output-name-format "{basename:cp}_{YYYY}-{MM}-{DD}.m3u" your_playlist_name.txt

# Or simply:

python playlist_maker_gui.py your_playlist_name.txt
```

## Version
Current version: **2.3.0**