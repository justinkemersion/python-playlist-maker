#!/usr/bin/env python3
# your_project_root/run_cli.py

import sys
from playlist_maker.app import main # Import the main function from your app module
from playlist_maker.ui.cli_interface import colorize, Colors # For potential error printing here

if __name__ == "__main__":
    try:
        # main() from app.py is expected to handle its own sys.argv parsing if argv_list is None
        # and return a dictionary like {"success": True/False, "error": "msg", "skipped_tracks": []}
        # or raise SystemExit for argparse errors (-h, bad args).
        
        # Call main and let it handle argument parsing from sys.argv by default
        # The argv_list parameter in app.main is for programmatic calls or testing.
        run_status = main() 

        if isinstance(run_status, dict) and not run_status.get("success", True):
            # If main explicitly returns a failure status, exit with 1.
            # Error messages should have been printed by main or its sub-components.
            if run_status.get("error"): # Optionally print error if main didn't already
                 print(colorize(f"Application failed: {run_status.get('error')}", Colors.RED), file=sys.stderr)
            sys.exit(1)
        # If main returns an integer, assume it's an exit code (though dict is preferred)
        elif isinstance(run_status, int):
            sys.exit(run_status)
        # If main completes without explicit failure in dict, assume success (exit 0).

    except SystemExit as se:
        # This catches sys.exit() called by argparse (e.g., for -h, --version, or bad arguments)
        # or explicit sys.exit() calls from within app.main or its called functions.
        sys.exit(se.code)
    except KeyboardInterrupt:
        print(colorize("\nProcess interrupted by user (Ctrl+C).", Colors.YELLOW))
        sys.exit(130) # Standard exit code for SIGINT
    except Exception as e_top:
        # This is a last-resort catch for truly unexpected errors not handled by app.main.
        # app.main should ideally log critical errors itself.
        # We can use logging here too if we configure a minimal handler for the runner.
        import logging
        # Assuming app.main's logging is already set up, this might be redundant or log to a different place.
        # For a truly isolated runner log, you'd init basicConfig here.
        logger = logging.getLogger("run_cli") # Get a logger instance
        logger.critical("Unhandled exception in run_cli.py top-level.", exc_info=True)
        
        print(colorize(f"\nCRITICAL UNHANDLED ERROR in runner: {e_top}", Colors.RED + Colors.BOLD), file=sys.stderr)
        print(colorize("This indicates a severe issue. Please check application logs.", Colors.RED), file=sys.stderr)
        sys.exit(1) # General error code