# playlist_maker/utils/logging_setup.py
import logging
import sys
import os
from pathlib import Path
from playlist_maker.ui.cli_interface import colorize, Colors # Import from the new location

def setup_logging(log_file_path: Path, log_mode: str): # Added type hints for clarity
    """Configures logging to file and console."""
    filemode = 'a' if log_mode == 'append' else 'w'
    log_file_str = ""
    try:
        log_parent_dir = log_file_path.parent
        log_parent_dir.mkdir(parents=True, exist_ok=True)
        log_file_str = str(log_file_path)
        if not os.access(log_parent_dir, os.W_OK):
             raise PermissionError(f"No write permission for log directory: {log_parent_dir}")
    except (PermissionError, OSError, Exception) as e:
        # Use the imported colorize and Colors
        print(colorize(f"Error preparing log file path {log_file_path}: {e}", Colors.RED), file=sys.stderr)
        try:
            fallback_path = Path.cwd() / log_file_path.name
            log_file_str = str(fallback_path)
            print(colorize(f"Attempting to log to fallback path: {log_file_str}", Colors.YELLOW), file=sys.stderr)
            if not os.access(Path(log_file_str).parent, os.W_OK):
                 print(colorize(f"ERROR: No write permission for fallback log directory either: {Path(log_file_str).parent}", Colors.RED), file=sys.stderr)
                 return
        except Exception as fallback_e:
             print(colorize(f"ERROR: Could not determine fallback log path: {fallback_e}", Colors.RED), file=sys.stderr)
             return

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        handler.close()

    try:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s",
            filename=log_file_str,
            filemode=filemode,
            force=True
        )
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        # Use the imported Colors
        formatter = logging.Formatter(f'{Colors.YELLOW}%(levelname)s:{Colors.RESET} [%(funcName)s] %(message)s')
        console_handler.setFormatter(formatter)
        logger = logging.getLogger()
        if not any(isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers):
             logger.addHandler(console_handler)

    except Exception as e:
         # Use the imported colorize and Colors
         print(colorize(f"ERROR: Exception during logging setup: {e}", Colors.RED), file=sys.stderr)