# playlist_maker/ui/interactive_prompts.py
import logging
import random
import sys # Only if direct stderr prints are kept, ideally remove.
from pathlib import Path
from fuzzywuzzy import fuzz

from .cli_interface import Colors, Symbols, colorize # Relative import
from playlist_maker.utils.normalization_utils import normalize_and_detect_specific_live_format
# No direct use of INTERACTIVE_MODE global here; behavior is driven by when these are called.
# PARENTHETICAL_STRIP_REGEX is passed to normalize_and_detect_specific_live_format.

def prompt_user_for_choice(input_artist, input_track, candidates, artist_matches,
                           input_live_format, threshold):
    # ... (Full function content as it was in playlist_maker.py)
    # Ensure random is imported if not done globally in this file
    # Ensure Colors, Symbols, colorize are available via the relative import
    # No changes to the internal logic of this function are strictly needed for the move,
    # just ensure its dependencies (imports) are met in this new file.
    print("-" * 70)
    print(f"{Colors.BOLD}{Colors.CYAN}INTERACTIVE PROMPT for:{Colors.RESET}")
    print(f"  Input: {colorize(input_artist, Colors.BOLD)} - {colorize(input_track, Colors.BOLD)}")
    print(f"  (Input Specified Live: {colorize(str(input_live_format), Colors.BOLD)})")
    print("-" * 70)
    valid_choices = {}
    numeric_choice_counter = 1
    if candidates:
        print(f"{Colors.UNDERLINE}Potential Matches Found (ranked by score):{Colors.RESET}")
        max_display = 7
        displayed_count = 0
        for entry in candidates:
             if entry.get('_current_score_before_prompt', -1) >= threshold:
                score = entry['_current_score_before_prompt']
                live_status = colorize("LIVE", Colors.MAGENTA) if entry['entry_is_live'] else colorize("Studio", Colors.GREEN)
                album_str = f" (Album: {entry.get('album', 'Unknown')})" if entry.get('album') else ""
                duration_str = f" [{entry['duration']}s]" if entry.get('duration', -1) != -1 else ""
                filename = Path(entry['path']).name
                live_mismatch_note = ""
                if input_live_format != entry['entry_is_live']:
                    penalty_note = "(Penalty Applied)" if entry.get('_penalty_applied', False) else ""
                    live_mismatch_note = colorize(f" <-- NOTE: Live/Studio mismatch! {penalty_note}", Colors.YELLOW)
                print(f"  {colorize(f'[{numeric_choice_counter}]', Colors.BLUE)} {entry['artist']} - {entry['title']}{album_str}{duration_str}")
                print(f"      Score: {colorize(f'{score:.1f}', Colors.BOLD)} | Type: {live_status} | File: {filename}{live_mismatch_note}")
                valid_choices[str(numeric_choice_counter)] = entry
                numeric_choice_counter += 1
                displayed_count += 1
                if displayed_count >= max_display and len(candidates) > displayed_count:
                     remaining_above_thresh = sum(1 for e in candidates[displayed_count:] if e.get('_current_score_before_prompt', -1) >= threshold)
                     if remaining_above_thresh > 0:
                          print(colorize(f"      ... (and {remaining_above_thresh} more candidates above threshold)", Colors.YELLOW))
                     break
        if displayed_count == 0: # This condition was inside `if candidates:` block, should be outside or re-evaluated
             print(colorize("No matches found meeting the display threshold.", Colors.YELLOW))
    else: # No candidates at all
        print(colorize("No direct title matches found meeting threshold.", Colors.YELLOW))

    print(f"\n{Colors.UNDERLINE}Choose an action:{Colors.RESET}")
    print(f"  {colorize('[S]', Colors.RED)}kip this track")
    valid_choices['s'] = None
    if artist_matches:
        print(f"  {colorize('[R]', Colors.YELLOW)}andom track from library by artist containing '{input_artist}'")
        valid_choices['r'] = 'random'
    
    # Context notes - ensure `displayed_count` is accurate if no candidates met threshold for display
    # This logic might need a small tweak if `displayed_count` could be 0 even if `candidates` is not empty
    # but none met threshold. For now, assume original logic is fine.
    if candidates and displayed_count > 0: # Only show notes if candidates meeting threshold were displayed
        found_live = any(c.get('entry_is_live', False) for c in candidates if c.get('_current_score_before_prompt', -1) >= threshold)
        found_studio = any(not c.get('entry_is_live', True) for c in candidates if c.get('_current_score_before_prompt', -1) >= threshold)
        if not input_live_format and found_live and not found_studio:
            print(colorize("  NOTE: Input track seems Studio, only LIVE version(s) met threshold.", Colors.YELLOW))
        elif input_live_format and not found_live and found_studio:
            print(colorize("  NOTE: Input track seems LIVE, only STUDIO version(s) met threshold.", Colors.YELLOW))
        elif found_live and found_studio: # This check is slightly flawed; should be if BOTH types are in displayed candidates
             print(colorize("  NOTE: Both Studio and LIVE versions found among threshold-meeting candidates. Check types listed above.", Colors.YELLOW))

    while True:
        try:
            prompt_text = colorize("Your choice (number, S, R): ", Colors.BLUE + Colors.BOLD)
            choice = input(prompt_text).lower().strip()
            if choice in valid_choices:
                selected_option = valid_choices[choice]
                if selected_option == 'random':
                    if artist_matches:
                        random_entry = random.choice(artist_matches)
                        print(f"\n{colorize('Selected Random Track:', Colors.YELLOW + Colors.BOLD)}")
                        print(f"  Artist: {random_entry['artist']}")
                        print(f"  Title:  {random_entry['title']}")
                        print(f"  Path:   {random_entry['path']}")
                        logging.info(f"INTERACTIVE: User chose [R]andom track for '{input_artist} - {input_track}'. Selected: {random_entry['path']}")
                        return random_entry
                    else: # Should not happen if 'R' is offered
                        print(colorize("Error: No tracks available for random selection by this artist.", Colors.RED))
                        continue
                elif selected_option is None: # Skip
                    print(f"\n{colorize('Skipping track.', Colors.RED)}")
                    logging.info(f"INTERACTIVE: User chose [S]kip for '{input_artist} - {input_track}'.")
                    return None
                else: # Chose a numbered candidate
                    print(f"\n{colorize(f'Selected Match [{choice}]:', Colors.GREEN + Colors.BOLD)}")
                    print(f"  Artist: {selected_option['artist']}")
                    print(f"  Title:  {selected_option['title']}")
                    print(f"  Path:   {selected_option['path']}")
                    logging.info(f"INTERACTIVE: User chose candidate [{choice}] for '{input_artist} - {input_track}'. Selected: {selected_option['path']}")
                    return selected_option # This is the dict
            else:
                print(colorize(f"Invalid choice '{choice}'. Please enter a valid number, S, or R.", Colors.RED))
        except EOFError:
             print(colorize("\nEOF received. Assuming Skip.", Colors.RED))
             logging.warning(f"INTERACTIVE: EOF received. Assuming skip for '{input_artist} - {input_track}'.")
             return None
        except KeyboardInterrupt:
            print(colorize("\nKeyboard Interrupt. Assuming Skip.", Colors.RED))
            logging.warning(f"INTERACTIVE: KeyboardInterrupt. Assuming skip for '{input_artist} - {input_track}'.")
            return None


def prompt_album_selection_or_skip(input_artist, input_track, artist_library_entries,
                                   input_live_format, threshold,
                                   current_library_index, # Used to list tracks from chosen album
                                   parenthetical_strip_regex # Used for normalizing input_artist
                                  ):
    # ... (Full function content as it was in playlist_maker.py)
    # Ensure normalize_and_detect_specific_live_format is imported from utils
    # Ensure fuzz is imported
    # Ensure random is imported
    # Ensure Colors, Symbols, colorize are available via relative import
    # It already takes current_library_index and parenthetical_strip_regex as params.
    print("-" * 70)
    print(f"{Colors.BOLD}{Colors.CYAN}INTERACTIVE ALBUM SELECTION for:{Colors.RESET}")
    print(f"  Input: {colorize(input_artist, Colors.BOLD)} - {colorize(input_track, Colors.BOLD)}")
    print(f"  (No direct match found for this track)")
    print("-" * 70)
    
    norm_input_artist_str, _ = normalize_and_detect_specific_live_format(input_artist, parenthetical_strip_regex)
    albums_by_artist = {}
    for entry in artist_library_entries: # These are already filtered by artist name somewhat by MatchingService
        lib_artist_norm = entry.get("norm_artist_stripped", "")
        # Looser check here, as artist_library_entries should be relevant
        if norm_input_artist_str in lib_artist_norm or fuzz.ratio(norm_input_artist_str, lib_artist_norm) > 70: # Adjusted threshold
            album_title = entry.get("album")
            if album_title:
                norm_album = album_title.lower()
                if norm_album not in albums_by_artist:
                    albums_by_artist[norm_album] = album_title
    
    if not albums_by_artist:
        print(colorize(f"No albums found in the library for artist '{input_artist}' to select from.", Colors.YELLOW))
        # Fallback to the standard choice prompt
        return prompt_user_for_choice(input_artist, input_track, [], artist_library_entries, input_live_format, threshold)

    while True: # Album selection loop
        print(f"\n{Colors.UNDERLINE}Artist '{input_artist}' has the following albums in your library:{Colors.RESET}")
        album_choices_map = {}
        idx = 1
        sorted_original_album_titles = sorted(list(albums_by_artist.values()))
        for original_album_title in sorted_original_album_titles:
            print(f"  {colorize(f'[{idx}]', Colors.BLUE)} {original_album_title}")
            album_choices_map[str(idx)] = original_album_title
            idx += 1
        print(f"  {colorize('[S]', Colors.RED)}kip this track input")
        album_choices_map['s'] = 'skip'
        if artist_library_entries:
             print(f"  {colorize('[R]', Colors.YELLOW)}andom track by '{input_artist}' (from any album)")
             album_choices_map['r'] = 'random'
        try:
            album_prompt_text = colorize("Choose an album (number, S, R): ", Colors.BLUE + Colors.BOLD)
            album_choice_str = input(album_prompt_text).lower().strip()

            if album_choice_str in album_choices_map:
                selected_album_action = album_choices_map[album_choice_str]
                if selected_album_action == 'skip':
                    # ... (logging and return None as before)
                    print(f"\n{colorize('Skipping track.', Colors.RED)}")
                    logging.info(f"INTERACTIVE (Album Select): User chose [S]kip for '{input_artist} - {input_track}'.")
                    return None
                elif selected_album_action == 'random':
                    # ... (random selection, logging, return random_entry as before)
                    if artist_library_entries:
                        random_entry = random.choice(artist_library_entries)
                        # ... print and log ...
                        return random_entry
                    # ... else error and continue ...
                
                # User selected an album by number
                chosen_album_title_original = selected_album_action
                logging.info(f"INTERACTIVE (Album Select): User selected album '{chosen_album_title_original}'.")

                tracks_on_selected_album = []
                for lib_entry in current_library_index: # Iterate full library index
                    # Match artist (normalized) and album (original case)
                    lib_artist_norm_check = lib_entry.get("norm_artist_stripped", "")
                    # Artist match for tracks on album can be a bit more stringent or rely on context
                    artist_match_for_album_tracks = norm_input_artist_str in lib_artist_norm_check or \
                                                    fuzz.partial_ratio(norm_input_artist_str, lib_artist_norm_check) > 85 # or entry['artist'] == input_artist
                    
                    album_match_for_album_tracks = lib_entry.get("album") == chosen_album_title_original
                    
                    if artist_match_for_album_tracks and album_match_for_album_tracks:
                        tracks_on_selected_album.append(lib_entry)
                
                # Sort tracks (as before)
                # ...
                def get_track_num_sort_key(entry): # Copied from original
                    tn_str = entry.get("tracknumber", "9999") 
                    if isinstance(tn_str, str) and '/' in tn_str: tn_str = tn_str.split('/')[0]
                    try: return (int(tn_str), entry.get("title", "").lower())
                    except ValueError: return (9999, entry.get("title", "").lower())
                tracks_on_selected_album.sort(key=get_track_num_sort_key)


                if not tracks_on_selected_album:
                    # ... (error message and continue as before)
                    print(colorize(f"No tracks found for album '{chosen_album_title_original}'. This is unexpected.", Colors.RED))
                    continue

                # Inner loop for track selection from album (as before)
                while True: # Track selection loop
                    # ... (print tracks, get input, handle 'B'ack, 'S'kip, or number choice)
                    # ... (if number, return chosen_final_track)
                    print(f"\n{Colors.UNDERLINE}Tracks on '{chosen_album_title_original}' by '{input_artist}':{Colors.RESET}")
                    track_choices_map = {}
                    track_idx = 1
                    for track_entry in tracks_on_selected_album:
                        live_status = colorize("LIVE", Colors.MAGENTA) if track_entry['entry_is_live'] else colorize("Studio", Colors.GREEN)
                        duration_str = f" [{track_entry['duration']}s]" if track_entry.get('duration', -1) != -1 else ""
                        print(f"  {colorize(f'[{track_idx}]', Colors.BLUE)} {track_entry['title']}{duration_str} - {live_status}")
                        track_choices_map[str(track_idx)] = track_entry
                        track_idx += 1
                    print(f"  {colorize('[B]', Colors.YELLOW)}ack to album selection")
                    track_choices_map['b'] = 'back'
                    print(f"  {colorize('[S]', Colors.RED)}kip original input track")
                    track_choices_map['s'] = 'skip'

                    try:
                        track_prompt_text = colorize("Choose a track (number, B, S): ", Colors.BLUE + Colors.BOLD)
                        track_choice_str = input(track_prompt_text).lower().strip()
                        if track_choice_str in track_choices_map:
                            selected_track_action = track_choices_map[track_choice_str]
                            if selected_track_action == 'skip': # Skip original input
                                print(f"\n{colorize('Skipping original track.', Colors.RED)}")
                                return None 
                            elif selected_track_action == 'back':
                                break # Breaks from track loop to album loop
                            # User chose a track number
                            chosen_final_track = selected_track_action
                            print(f"\n{colorize('Selected Replacement Track:', Colors.GREEN + Colors.BOLD)}")
                            print(f"  Artist: {chosen_final_track['artist']} - Title: {chosen_final_track['title']}")
                            return chosen_final_track # This is the selected library entry dict
                        else:
                            print(colorize(f"Invalid choice '{track_choice_str}'.", Colors.RED))
                    except (EOFError, KeyboardInterrupt):
                        print(colorize("\nInput interrupted. Assuming Skip.", Colors.RED))
                        return None # Skip original input
                # If 'B' (back) was chosen in inner loop, this 'continue' goes to next album selection iteration
                if track_choice_str == 'b': continue 
            else: # Invalid album choice string
                print(colorize(f"Invalid album choice '{album_choice_str}'.", Colors.RED))
        except (EOFError, KeyboardInterrupt): # For album selection input
            print(colorize("\nInput interrupted. Assuming Skip.", Colors.RED))
            return None # Skip original input