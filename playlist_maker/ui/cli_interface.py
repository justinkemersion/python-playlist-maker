# playlist_maker/ui/cli_interface.py
import sys

_IS_TTY = sys.stdout.isatty() # Basic check if we're likely in a TTY

class Colors:
    RESET = "\033[0m" if _IS_TTY else ""
    RED = "\033[91m" if _IS_TTY else ""
    GREEN = "\033[92m" if _IS_TTY else ""
    YELLOW = "\033[93m" if _IS_TTY else ""
    BLUE = "\033[94m" if _IS_TTY else ""
    MAGENTA = "\033[95m" if _IS_TTY else ""
    CYAN = "\033[96m" if _IS_TTY else ""
    BOLD = "\033[1m" if _IS_TTY else ""
    UNDERLINE = "\033[4m" if _IS_TTY else ""

class Symbols:
    SUCCESS = "[✔]" if _IS_TTY else "[+]"
    FAILURE = "[✘]" if _IS_TTY else "[-]"
    WARNING = "[!]" if _IS_TTY else "[!]"
    INFO    = "[i]" if _IS_TTY else "[i]" # Simple 'i'
    ARROW   = "[→]" if _IS_TTY else "->"
    BULLET  = "[•]" if _IS_TTY else "*"  # For list items in prompts
    ELLIPSIS= "..."

def colorize(text, color_code):
    """Wraps text with ANSI color codes, if supported."""
    return f"{color_code}{text}{Colors.RESET}"

# We can also move prompt_user_for_choice and prompt_album_selection_or_skip here later,
# but let's do these simple ones first.