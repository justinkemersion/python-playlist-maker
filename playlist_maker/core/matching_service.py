# playlist_maker/core/matching_service.py
import logging
from pathlib import Path
from fuzzywuzzy import fuzz # Make sure this is available or add to requirements

# Normalization utils are needed
from playlist_maker.utils.normalization_utils import normalize_and_detect_specific_live_format
# We won't call UI prompts from here directly, so no UI imports.

# For type hinting the return value when interaction is needed
from typing import List, Dict, Any, Tuple, Optional, Union

# Define a structure for what to return when interaction is needed
class InteractionRequired:
    def __init__(self, reason: str, candidates: List[Dict[str, Any]],
                 artist_matches: List[Dict[str, Any]],
                 input_artist: str, input_track: str,
                 is_input_explicitly_live_format: bool, match_threshold: int):
        self.reason = reason # e.g., "no_direct_match", "multiple_qualified_matches"
        self.candidates = candidates
        self.artist_matches = artist_matches
        self.input_artist = input_artist
        self.input_track = input_track
        self.is_input_explicitly_live_format = is_input_explicitly_live_format
        self.match_threshold = match_threshold

class MatchingService:
    def __init__(self, interactive_mode: bool):
        self.interactive_mode = interactive_mode
        # Potentially store live_penalty_factor if it's constant for the service instance
        # self.live_penalty_factor = live_penalty_factor # If passed during init

    def find_best_track_match(
        self,
        input_artist: str,
        input_track: str,
        match_threshold: int,
        live_penalty_factor: float, # Pass it per call, or set during __init__
        current_library_index: List[Dict[str, Any]],
        parenthetical_strip_regex # Compiled regex
    ) -> Union[Optional[Dict[str, Any]], InteractionRequired]: # Return type

        norm_input_artist_match_str, input_artist_has_live_format = normalize_and_detect_specific_live_format(input_artist, parenthetical_strip_regex)
        norm_input_title_match_str, input_title_has_live_format = normalize_and_detect_specific_live_format(input_track, parenthetical_strip_regex)
        is_input_explicitly_live_format = input_artist_has_live_format or input_title_has_live_format

        logging.debug(f"MATCH_SVC: BEGIN SEARCH (Interactive: {self.interactive_mode}): For Input='{input_artist} - {input_track}' (InputLiveFmt: {is_input_explicitly_live_format})")
        logging.debug(f"  Norm Input Match: Artist='{norm_input_artist_match_str}', Title='{norm_input_title_match_str}'")

        candidate_artist_entries = []
        processed_artists_for_debug = set()
        best_artist_substring_miss_entry, best_artist_substring_miss_score = None, -1

        for entry in current_library_index:
            norm_library_artist_stripped = entry["norm_artist_stripped"]
            if norm_input_artist_match_str and norm_library_artist_stripped and norm_input_artist_match_str in norm_library_artist_stripped:
                candidate_artist_entries.append(entry)
                if norm_library_artist_stripped not in processed_artists_for_debug:
                    logging.debug(f"  Artist Substring Candidate: Input '{norm_input_artist_match_str}' in Lib Artist '{norm_library_artist_stripped}' (Path: {entry['path']})")
                    processed_artists_for_debug.add(norm_library_artist_stripped)
            elif not norm_input_artist_match_str and not norm_library_artist_stripped:
                 candidate_artist_entries.append(entry)
                 if "UNKNOWN_ARTIST_EMPTY_INPUT" not in processed_artists_for_debug:
                     logging.debug(f"  Artist Empty Match: Path: {entry['path']}")
                     processed_artists_for_debug.add("UNKNOWN_ARTIST_EMPTY_INPUT")
            else:
                 if norm_input_artist_match_str and norm_library_artist_stripped:
                    current_artist_fuzzy_score = fuzz.ratio(norm_input_artist_match_str, norm_library_artist_stripped)
                    if current_artist_fuzzy_score > best_artist_substring_miss_score:
                        best_artist_substring_miss_score = current_artist_fuzzy_score
                        best_artist_substring_miss_entry = entry
        
        if not candidate_artist_entries:
            miss_info = f"MATCH_SVC: NO ARTIST MATCH: Input artist '{input_artist}' (Norm: '{norm_input_artist_match_str}') not found."
            # ... (logging as before) ...
            logging.warning(miss_info)
            if self.interactive_mode:
                return InteractionRequired(
                    reason="no_artist_match", candidates=[], artist_matches=[],
                    input_artist=input_artist, input_track=input_track,
                    is_input_explicitly_live_format=is_input_explicitly_live_format,
                    match_threshold=match_threshold
                )
            return None

        logging.info(f"MATCH_SVC: Found {len(candidate_artist_entries)} entries for artist '{input_artist}'. Matching title '{input_track}'.")

        scored_candidates = []
        all_title_misses_for_logging = []

        for entry in candidate_artist_entries:
            title_meta_score = fuzz.ratio(norm_input_title_match_str, entry["norm_title_stripped"]) if entry["norm_title_stripped"] else -1
            filename_score_for_title = fuzz.token_set_ratio(norm_input_title_match_str, entry["norm_filename_stripped"])
            logging.debug(f"  Testing entry '{Path(entry['path']).name}' (Live: {entry['entry_is_live']}): TitleScore={title_meta_score}, FilenameScore={filename_score_for_title}")
            current_base_score = max(title_meta_score, filename_score_for_title)

            if current_base_score >= (match_threshold - 15):
                adjusted_score = current_base_score
                if entry["norm_artist_stripped"] == norm_input_artist_match_str:
                    artist_bonus = 1.0
                else:
                    library_artist_match_to_input_artist = fuzz.ratio(norm_input_artist_match_str, entry["norm_artist_stripped"])
                    artist_bonus = (library_artist_match_to_input_artist / 100.0) * 0.5
                adjusted_score += artist_bonus
                adjusted_score = min(adjusted_score, 100.0)

                original_score_before_penalty = adjusted_score
                penalty_applied = False
                if not is_input_explicitly_live_format and entry["entry_is_live"]:
                    adjusted_score *= live_penalty_factor
                    penalty_applied = True
                    logging.debug(f"      Applied Live Penalty: {original_score_before_penalty:.1f} * {live_penalty_factor} -> {adjusted_score:.1f}")
                
                entry['_current_score_before_prompt'] = adjusted_score # Keep for sorting
                entry['_original_score'] = original_score_before_penalty
                entry['_penalty_applied'] = penalty_applied
                scored_candidates.append(entry)
            else:
                all_title_misses_for_logging.append((current_base_score, entry))
                logging.debug(f"    Candidate Base Score Too Low (Base: {current_base_score:.1f}, Path: {entry['path']})")

        qualified_candidates = [c for c in scored_candidates if c.get('_current_score_before_prompt', -1) >= match_threshold]
        qualified_candidates.sort(key=lambda x: x.get('_current_score_before_prompt', -1), reverse=True)

        if not qualified_candidates:
            log_msg = f"MATCH_SVC: NO DIRECT MATCH for '{input_artist} - {input_track}' meeting threshold {match_threshold}."
            # ... (logging as before) ...
            logging.warning(log_msg)
            if self.interactive_mode and candidate_artist_entries: # No direct match, but artist has tracks
                return InteractionRequired(
                    reason="no_direct_match_album_selection_possible",
                    candidates=[], # No qualified direct matches
                    artist_matches=candidate_artist_entries, # For album/random selection
                    input_artist=input_artist, input_track=input_track,
                    is_input_explicitly_live_format=is_input_explicitly_live_format,
                    match_threshold=match_threshold
                )
            elif self.interactive_mode: # No artist context or other issue
                 return InteractionRequired(
                    reason="no_direct_match_basic_skip_random",
                    candidates=scored_candidates, # Pass all scored for potential display
                    artist_matches=candidate_artist_entries,
                    input_artist=input_artist, input_track=input_track,
                    is_input_explicitly_live_format=is_input_explicitly_live_format,
                    match_threshold=match_threshold
                )
            return None # Not interactive, no qualified match

        # We have qualified candidates
        if not self.interactive_mode or len(qualified_candidates) == 1:
            best_overall_match = None
            best_candidate_of_correct_live_type = None
            best_candidate_of_other_live_type = None
            for cand in qualified_candidates:
                if cand['entry_is_live'] == is_input_explicitly_live_format:
                    if best_candidate_of_correct_live_type is None or \
                       cand['_current_score_before_prompt'] > best_candidate_of_correct_live_type['_current_score_before_prompt']:
                        best_candidate_of_correct_live_type = cand
                else:
                    if best_candidate_of_other_live_type is None or \
                       cand['_current_score_before_prompt'] > best_candidate_of_other_live_type['_current_score_before_prompt']:
                        best_candidate_of_other_live_type = cand
            
            if best_candidate_of_correct_live_type: best_overall_match = best_candidate_of_correct_live_type
            elif best_candidate_of_other_live_type: best_overall_match = best_candidate_of_other_live_type
            else: best_overall_match = qualified_candidates[0] # Should not happen if qualified_candidates not empty

            if best_overall_match:
                logging.info(f"MATCH_SVC: MATCHED (Auto/Single Direct): '{input_artist} - {input_track}' -> '{best_overall_match['path']}' Score: {best_overall_match.get('_current_score_before_prompt', -1):.1f}")
                # Clean up temporary keys before returning
                clean_entry = {k: v for k, v in best_overall_match.items() if not k.startswith('_')}
                return clean_entry
            return None
        else: # Interactive mode AND multiple QUALIFIED direct track candidates
            logging.info(f"MATCH_SVC: Multiple ({len(qualified_candidates)}) qualified direct matches. Returning InteractionRequired.")
            return InteractionRequired(
                reason="multiple_qualified_matches",
                candidates=qualified_candidates,
                artist_matches=candidate_artist_entries,
                input_artist=input_artist, input_track=input_track,
                is_input_explicitly_live_format=is_input_explicitly_live_format,
                match_threshold=match_threshold
            )