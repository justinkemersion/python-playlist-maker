# playlist_maker/ui/interactive_prompts.py
import logging
import random
import sys
from pathlib import Path
from fuzzywuzzy import fuzz # Used in prompt_album_selection_or_skip

from .cli_interface import Colors, Symbols, colorize
from playlist_maker.utils.normalization_utils import normalize_and_detect_specific_live_format # Used in prompt_album_selection_or_skip

def prompt_user_for_choice(input_artist, input_track, candidates, artist_matches,
                           input_live_format, threshold):
    """ Presents choices to the user, Enter defaults to Skip. """
    print("-" * 70)
    print(f"{Colors.BOLD}{Colors.CYAN}INTERACTIVE PROMPT for:{Colors.RESET}")
    print(f"  Input: {colorize(input_artist, Colors.BOLD)} - {colorize(input_track, Colors.BOLD)}")
    print(f"  (Input Specified Live: {colorize(str(input_live_format), Colors.BOLD)})")
    print("-" * 70)

    valid_choices = {}
    numeric_choice_counter = 1
    displayed_candidate_count = 0

    if candidates:
        print(f"{Colors.UNDERLINE}Potential Matches Found (ranked by score):{Colors.RESET}")
        max_display = 7
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
                displayed_candidate_count += 1
                if displayed_candidate_count >= max_display and len([c for c in candidates if c.get('_current_score_before_prompt', -1) >= threshold]) > displayed_candidate_count:
                    remaining_above_thresh = sum(1 for e in candidates[displayed_candidate_count:] if e.get('_current_score_before_prompt', -1) >= threshold)
                    if remaining_above_thresh > 0:
                        print(colorize(f"      ... (and {remaining_above_thresh} more candidates above threshold)", Colors.YELLOW))
                    break
        if displayed_candidate_count == 0 and candidates:
            print(colorize("No matches found meeting the display threshold (adjust threshold or input for better results).", Colors.YELLOW))
    
    if not candidates:
        print(colorize("No direct title matches found by the matching service.", Colors.YELLOW))

    print(f"\n{Colors.UNDERLINE}Choose an action:{Colors.RESET}")
    valid_choices['s'] = None # Skip action

    prompt_options_list = ["S (default Enter)"] # Start building prompt options
    print(f"  {colorize('[S]', Colors.RED)}kip this track (default: Enter)")

    if artist_matches:
        print(f"  {colorize('[R]', Colors.YELLOW)}andom track from library by artist containing '{input_artist}'")
        valid_choices['r'] = 'random'
        prompt_options_list.append("R")
    
    if displayed_candidate_count > 0: # If there are numbered choices
        # Insert "number" at the beginning if it's not already there (it won't be)
        if "number" not in prompt_options_list: # Defensive check
             prompt_options_list.insert(0, "number")


    # Context Notes
    if displayed_candidate_count > 0:
        displayed_candidates_list = [entry for entry in candidates if entry.get('_current_score_before_prompt', -1) >= threshold][:displayed_candidate_count]
        found_live_in_displayed = any(c.get('entry_is_live', False) for c in displayed_candidates_list)
        found_studio_in_displayed = any(not c.get('entry_is_live', True) for c in displayed_candidates_list)
        if not input_live_format and found_live_in_displayed and not found_studio_in_displayed:
            print(colorize("  NOTE: Input track seems Studio, only LIVE version(s) were displayed.", Colors.YELLOW))
        elif input_live_format and not found_live_in_displayed and found_studio_in_displayed:
            print(colorize("  NOTE: Input track seems LIVE, only STUDIO version(s) were displayed.", Colors.YELLOW))
        elif found_live_in_displayed and found_studio_in_displayed:
            print(colorize("  NOTE: Both Studio and LIVE versions were displayed. Check types listed above.", Colors.YELLOW))

    while True:
        try:
            prompt_text_core = "/".join(prompt_options_list)
            prompt_text = colorize(f"Your choice ({prompt_text_core}): ", Colors.BLUE + Colors.BOLD)
            
            raw_choice = input(prompt_text).lower().strip()
            choice_was_empty_default = False

            if not raw_choice:  # User pressed Enter without typing anything
                choice = 's'    # Default to 's' (Skip)
                choice_was_empty_default = True
                print(colorize(f"No input, defaulting to Skip.", Colors.YELLOW)) 
            else:
                choice = raw_choice

            if choice in valid_choices:
                selected_option = valid_choices[choice]

                if selected_option == 'random':
                    if artist_matches: # Safeguard, should be true if 'r' was an option
                        random_entry = random.choice(artist_matches)
                        print(f"\n{colorize('Selected Random Track:', Colors.YELLOW + Colors.BOLD)}")
                        print(f"  Artist: {random_entry['artist']}")
                        print(f"  Title:  {random_entry['title']}")
                        print(f"  Path:   {random_entry['path']}")
                        logging.info(f"INTERACTIVE: User chose [R]andom track for '{input_artist} - {input_track}'. Selected: {random_entry['path']}")
                        return random_entry
                    else:
                        logging.error(f"INTERACTIVE: 'R' selected for '{input_artist} - {input_track}' but artist_matches was empty (should not happen).")
                        # Remove 'r' from options if this faulty state is reached
                        valid_choices.pop('r', None)
                        prompt_options_list = [opt for opt in prompt_options_list if opt != "R"]
                        continue # Re-prompt

                elif selected_option is None: # User chose 's' (Skip) or defaulted to it
                    skip_method = "defaulted to Skip" if choice_was_empty_default else "chose [S]kip"
                    print(f"\n{colorize('Skipping track.', Colors.RED)}")
                    logging.info(f"INTERACTIVE: User {skip_method} for '{input_artist} - {input_track}'.")
                    return None

                else: # User chose a numbered candidate
                    print(f"\n{colorize(f'Selected Match [{choice}]:', Colors.GREEN + Colors.BOLD)}")
                    print(f"  Artist: {selected_option['artist']}")
                    print(f"  Title:  {selected_option['title']}")
                    print(f"  Path:   {selected_option['path']}")
                    logging.info(f"INTERACTIVE: User chose candidate [{choice}] ('{selected_option['path']}') for '{input_artist} - {input_track}'.")
                    return selected_option
            else:
                print(colorize(f"Invalid choice '{choice}'. Please enter a valid option from ({prompt_text_core}).", Colors.RED))
        except EOFError:
            print(colorize("\nEOF received. Assuming Skip.", Colors.RED))
            logging.warning(f"INTERACTIVE: EOF received during prompt for '{input_artist} - {input_track}'. Assuming skip.")
            return None
        except KeyboardInterrupt:
            print(colorize("\nKeyboard Interrupt. Assuming Skip.", Colors.RED))
            logging.warning(f"INTERACTIVE: KeyboardInterrupt during prompt for '{input_artist} - {input_track}'. Assuming skip.")
            return None

def prompt_album_selection_or_skip(input_artist, input_track, artist_library_entries,
                                   input_live_format, threshold,
                                   current_library_index,
                                   parenthetical_strip_regex):
    print("-" * 70)
    print(f"{Colors.BOLD}{Colors.CYAN}INTERACTIVE ALBUM SELECTION for:{Colors.RESET}")
    print(f"  Input: {colorize(input_artist, Colors.BOLD)} - {colorize(input_track, Colors.BOLD)}")
    print(f"  (No direct match found for this track)")
    print("-" * 70)
    
    norm_input_artist_str, _ = normalize_and_detect_specific_live_format(input_artist, parenthetical_strip_regex)
    albums_by_artist = {} # { "normalized_album_title": "Original Album Title String" }
    for entry in artist_library_entries:
        lib_artist_norm = entry.get("norm_artist_stripped", "")
        if norm_input_artist_str in lib_artist_norm or fuzz.ratio(norm_input_artist_str, lib_artist_norm) > 70:
            album_title = entry.get("album")
            if album_title:
                norm_album = album_title.lower()
                if norm_album not in albums_by_artist:
                    albums_by_artist[norm_album] = album_title
    
    if not albums_by_artist:
        print(colorize(f"No albums found in the library for artist '{input_artist}' to select from.", Colors.YELLOW))
        # Fallback to the standard choice prompt (which now also has default Enter=Skip)
        return prompt_user_for_choice(input_artist, input_track, [], artist_library_entries, input_live_format, threshold)

    # Album selection loop
    while True:
        print(f"\n{Colors.UNDERLINE}Artist '{input_artist}' has the following albums in your library:{Colors.RESET}")
        album_choices_map = {}
        album_prompt_options_list = ["S (default Enter)"] # Default for album choice is also Skip

        idx = 1
        sorted_original_album_titles = sorted(list(albums_by_artist.values()))
        for original_album_title in sorted_original_album_titles:
            print(f"  {colorize(f'[{idx}]', Colors.BLUE)} {original_album_title}")
            album_choices_map[str(idx)] = original_album_title
            idx += 1
        
        if idx > 1: # If there were albums listed (numbered choices)
            if "number" not in album_prompt_options_list: # Should not be there yet
                album_prompt_options_list.insert(0, "number")


        print(f"  {colorize('[S]', Colors.RED)}kip this track input (default: Enter)")
        album_choices_map['s'] = 'skip' # Action for 's'

        if artist_library_entries:
            print(f"  {colorize('[R]', Colors.YELLOW)}andom track by '{input_artist}' (from any album)")
            album_choices_map['r'] = 'random'
            album_prompt_options_list.append("R")

        try:
            album_prompt_text_core = "/".join(album_prompt_options_list)
            album_prompt_text = colorize(f"Choose an album ({album_prompt_text_core}): ", Colors.BLUE + Colors.BOLD)
            
            raw_album_choice_str = input(album_prompt_text).lower().strip()
            album_choice_was_empty_default = False

            if not raw_album_choice_str:
                album_choice_str = 's' # Default to skip
                album_choice_was_empty_default = True
                print(colorize(f"No input, defaulting to Skip current track.", Colors.YELLOW))
            else:
                album_choice_str = raw_album_choice_str

            if album_choice_str in album_choices_map:
                selected_album_action = album_choices_map[album_choice_str]

                if selected_album_action == 'skip':
                    skip_method = "defaulted to Skip" if album_choice_was_empty_default else "chose [S]kip"
                    print(f"\n{colorize('Skipping track.', Colors.RED)}")
                    logging.info(f"INTERACTIVE (Album Select): User {skip_method} for '{input_artist} - {input_track}'.")
                    return None
                elif selected_album_action == 'random':
                    if artist_library_entries: # Safeguard
                        random_entry = random.choice(artist_library_entries)
                        print(f"\n{colorize('Selected Random Track:', Colors.YELLOW + Colors.BOLD)}")
                        print(f"  Artist: {random_entry['artist']} - Title: {random_entry['title']} (Album: {random_entry.get('album', 'N/A')})")
                        logging.info(f"INTERACTIVE (Album Select): User chose [R]andom track for '{input_artist} - {input_track}'. Selected: {random_entry['path']}")
                        return random_entry
                    else: # Should not be reachable if 'R' was offered correctly
                        logging.error(f"INTERACTIVE (Album Select): 'R' selected but artist_library_entries empty for '{input_artist}'.")
                        album_choices_map.pop('r', None)
                        album_prompt_options_list = [opt for opt in album_prompt_options_list if opt != "R"]
                        continue

                # User selected an album by number
                chosen_album_title_original = selected_album_action
                logging.info(f"INTERACTIVE (Album Select): User selected album '{chosen_album_title_original}' for '{input_artist} - {input_track}'.")

                tracks_on_selected_album = []
                for lib_entry in current_library_index:
                    lib_artist_norm_check = lib_entry.get("norm_artist_stripped", "")
                    artist_match_for_album_tracks = norm_input_artist_str in lib_artist_norm_check or \
                                                    fuzz.partial_ratio(norm_input_artist_str, lib_artist_norm_check) > 85
                    album_match_for_album_tracks = lib_entry.get("album") == chosen_album_title_original
                    if artist_match_for_album_tracks and album_match_for_album_tracks:
                        tracks_on_selected_album.append(lib_entry)
                
                def get_track_num_sort_key(entry):
                    tn_str = entry.get("tracknumber", "9999") 
                    if isinstance(tn_str, str) and '/' in tn_str: tn_str = tn_str.split('/')[0]
                    try: return (int(tn_str), entry.get("title", "").lower())
                    except ValueError: return (9999, entry.get("title", "").lower())
                tracks_on_selected_album.sort(key=get_track_num_sort_key)

                if not tracks_on_selected_album:
                    print(colorize(f"No tracks found in library for album '{chosen_album_title_original}' by '{input_artist}'. This is unexpected.", Colors.RED))
                    logging.error(f"INTERACTIVE (Album Select): No tracks found for album '{chosen_album_title_original}' after selection.")
                    continue # Go back to album selection

                # Inner loop for track selection from this album
                while True:
                    print(f"\n{Colors.UNDERLINE}Tracks on '{chosen_album_title_original}' by '{input_artist}':{Colors.RESET}")
                    track_choices_map = {}
                    track_prompt_options_list = ["S (default Enter)", "B"] # Default Skip, Back always an option

                    track_idx = 1
                    for track_entry_item in tracks_on_selected_album:
                        live_status = colorize("LIVE", Colors.MAGENTA) if track_entry_item['entry_is_live'] else colorize("Studio", Colors.GREEN)
                        duration_str = f" [{track_entry_item['duration']}s]" if track_entry_item.get('duration', -1) != -1 else ""
                        print(f"  {colorize(f'[{track_idx}]', Colors.BLUE)} {track_entry_item['title']}{duration_str} - {live_status}")
                        track_choices_map[str(track_idx)] = track_entry_item
                        track_idx += 1
                    
                    if track_idx > 1: # If tracks were listed
                        if "number" not in track_prompt_options_list:
                            track_prompt_options_list.insert(0, "number")
                    
                    print(f"  {colorize('[B]', Colors.YELLOW)}ack to album selection")
                    track_choices_map['b'] = 'back'
                    print(f"  {colorize('[S]', Colors.RED)}kip original input track (default: Enter)")
                    track_choices_map['s'] = 'skip' # Action for 's' (skip original input track)

                    try:
                        track_prompt_text_core = "/".join(track_prompt_options_list)
                        track_prompt_text = colorize(f"Choose a track ({track_prompt_text_core}): ", Colors.BLUE + Colors.BOLD)
                        
                        raw_track_choice_str = input(track_prompt_text).lower().strip()
                        track_choice_was_empty_default = False

                        if not raw_track_choice_str:
                            track_choice_str = 's' # Default to skip original track
                            track_choice_was_empty_default = True
                            print(colorize(f"No input, defaulting to Skip original track.", Colors.YELLOW))
                        else:
                            track_choice_str = raw_track_choice_str

                        if track_choice_str in track_choices_map:
                            selected_track_action = track_choices_map[track_choice_str]

                            if selected_track_action == 'skip':
                                skip_method = "defaulted to Skip" if track_choice_was_empty_default else "chose [S]kip"
                                print(f"\n{colorize('Skipping original track.', Colors.RED)}")
                                logging.info(f"INTERACTIVE (Album Track Select): User {skip_method} original input for '{input_artist} - {input_track}'.")
                                return None # Propagates to skip original input track
                            elif selected_track_action == 'back':
                                logging.info(f"INTERACTIVE (Album Track Select): User chose [B]ack to album selection.")
                                break # Breaks from track selection loop, goes back to album selection loop
                            
                            # User chose a track by number from this album
                            chosen_final_track = selected_track_action
                            print(f"\n{colorize('Selected Replacement Track:', Colors.GREEN + Colors.BOLD)}")
                            print(f"  Artist: {chosen_final_track['artist']} - Title: {chosen_final_track['title']} (Album: {chosen_final_track.get('album', 'N/A')})")
                            logging.info(f"INTERACTIVE (Album Track Select): User CHOSE track '{chosen_final_track['path']}' as replacement for '{input_artist} - {input_track}'.")
                            return chosen_final_track
                        else:
                            print(colorize(f"Invalid choice '{track_choice_str}'. Please enter a valid option from ({track_prompt_text_core}).", Colors.RED))
                    except (EOFError, KeyboardInterrupt):
                        print(colorize("\nInput interrupted. Assuming Skip original track.", Colors.RED))
                        logging.warning(f"INTERACTIVE (Album Track Select): EOF/KeyboardInterrupt. Assuming skip for '{input_artist} - {input_track}'.")
                        return None # Skip original input track
                
                # If we broke from inner loop due to 'B' (back), continue outer album selection loop
                if track_choice_str == 'b': 
                    continue 
            
            else: # Invalid album choice string from album_choices_map
                print(colorize(f"Invalid choice '{album_choice_str}'. Please enter a valid option from ({album_prompt_text_core}).", Colors.RED))

        except (EOFError, KeyboardInterrupt): # For album selection input
            print(colorize("\nInput interrupted. Assuming Skip original track.", Colors.RED))
            logging.warning(f"INTERACTIVE (Album Select): EOF/KeyboardInterrupt. Assuming skip for '{input_artist} - {input_track}'.")
            return None # Skip original input track
    # End of album selection loop (while True)