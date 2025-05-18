# playlist_maker/config/manager.py
import configparser
from pathlib import Path
import re
import logging
import os # For Path.home() if not directly using Path.home() for CONFIG_DIR_USER

# --- Configuration File Handling ---
CONFIG_FILENAME_LOCAL = "playlist_maker.conf" # Relative to script/package
CONFIG_FILENAME_USER = "config.ini" # Or "playlist_maker.conf" if you prefer consistency
# To make CONFIG_DIR_USER truly independent, it should resolve Path.home() here
CONFIG_DIR_USER = Path.home() / ".config" / "playlist-maker"

# Initialize config parser with a list converter
def parse_list(value):
    # Split by comma or whitespace, filter empty strings
    return [item.strip() for item in re.split(r'[,\s]+', value) if item.strip()]

config = configparser.ConfigParser(
    interpolation=None,
    converters={'list': parse_list}
)

# --- Config Helper Function ---
def get_config_value(section, option, fallback=None, expected_type=str): # Renamed slightly for clarity
    """
    Retrieves a value from the loaded configparser object. Handles type conversion and fallbacks.
    Uses the 'config' object defined in this module.
    """
    value = None
    raw_value_for_log = "N/A"
    try:
        if expected_type == bool:
            value = config.getboolean(section, option)
        elif expected_type == int:
            value = config.getint(section, option)
        elif expected_type == float:
            value = config.getfloat(section, option)
        elif expected_type == list:
            value = config.getlist(section, option) # Uses the custom converter
        else: # Default to string
             value = config.get(section, option, fallback=None)
             if value == "":
                 logging.debug(f"Config: [{section}] {option} is empty. Using fallback: {fallback}")
                 return fallback
             elif value is None:
                 return fallback

        return value

    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback
    except ValueError as e:
        try:
            raw_value_for_log = config.get(section, option, raw=True)
        except:
            raw_value_for_log = "[Could not retrieve raw value]"
        logging.warning(f"Config Error: Invalid value for [{section}] {option} = '{raw_value_for_log}'. "
                        f"Could not convert to {expected_type.__name__}. Using fallback: {fallback}. Error: {e}")
        return fallback
    except Exception as e:
        logging.error(f"Config Error: Unexpected error reading [{section}] {option}. "
                      f"Using fallback: {fallback}. Error: {e}", exc_info=True)
        return fallback

def load_config_files(project_root_path: Path):

    config_path_local = project_root_path / CONFIG_FILENAME_LOCAL # Assumes .conf is at project root
    config_path_user_resolved = CONFIG_DIR_USER / CONFIG_FILENAME_USER # CONFIG_DIR_USER already Path.home()

    try:
        CONFIG_DIR_USER.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # This print should ideally be a log or handled by the caller
        print(f"Warning: Could not create user config directory {CONFIG_DIR_USER}: {e}", file=sys.stderr) # Needs sys import

    loaded_files = config.read([config_path_local, config_path_user_resolved])
    if loaded_files:
        logging.info(f"Configuration files loaded: {', '.join(str(p) for p in loaded_files)}")
    else:
        logging.info("No configuration files found or read.")
    return loaded_files # Return list of successfully read files for info