# playlist_maker/utils/normalization_utils.py
import unicodedata
import re
import logging

# PARENTHETICAL_STRIP_REGEX is currently a global.
# Option 1: Pass it as an argument to functions that use it. (Preferred)
# Option 2: Have a setter function in this module if it's a module-level constant.
# Option 3: Import it if it becomes a constant defined elsewhere.

# Let's go with Option 1 for normalize_and_detect_specific_live_format.

def normalize_and_detect_specific_live_format(s, parenthetical_strip_regex=None): # Added regex as param
    """
    Normalizes a string for matching (handling '&', '/', 'and', feat., common suffixes in parens, leading articles)
    and specifically detects if it contains '(live)' format in the original casing structure.
    Returns normalized string for matching and a boolean for live detection.
    Uses the provided parenthetical_strip_regex.
    """
    # global PARENTHETICAL_STRIP_REGEX # Remove this global usage

    if not isinstance(s, str): return "", False

    original_s_lower_for_live_check = s.lower()
    is_live_format = bool(re.search(r'\(\s*live[\s\W]*\)', original_s_lower_for_live_check, re.IGNORECASE))

    try:
        normalized_s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    except TypeError:
        logging.warning(f"Normalization failed for non-string input: {s}")
        return "", False

    s_for_matching = normalized_s.lower()
    logging.debug(f"Norm Step 1 (Input='{s}'): NFD+Lower='{s_for_matching}' | LiveFormatDetected={is_live_format}")

    s_for_matching = re.sub(r"^(the|a|an)\s+", "", s_for_matching, flags=re.IGNORECASE, count=1).strip()
    logging.debug(f"Norm Step 1b (Strip Articles): -> '{s_for_matching}'")

    s_for_matching = re.sub(r'\s*&\s*', ' ', s_for_matching) # "&"
    s_for_matching = re.sub(r'\s*/\s*', ' ', s_for_matching) # "/"
    s_for_matching = re.sub(r'\s+and\s+', ' ', s_for_matching) # "and"
    logging.debug(f"Norm Step 2 (Replace '&/and'): -> '{s_for_matching}'")

    s_for_matching = re.sub(r'^\s*\d{1,3}[\s.-]+\s*', '', s_for_matching).strip() # Leading track numbers
    logging.debug(f"Norm Step 3 (Strip TrackNum): -> '{s_for_matching}'")

    def process_parenthetical_content(match):
        content = match.group(1).strip().lower()
        logging.debug(f"Norm Step 4a (Examining Parenthesis): Content='{content}'")

        if re.fullmatch(r'live[\s\W]*', content, re.IGNORECASE):
            logging.debug(f"  -> Parenthesis: Keeping 'live' token.")
            return ' live '

        feat_match = re.match(r'(?:feat|ft|featuring|with)\.?\s*(.*)', content, re.IGNORECASE)
        if feat_match:
            feat_artist = feat_match.group(1).strip()
            feat_artist_norm = ''.join(c for c in feat_artist if c.isalnum() or c.isspace())
            feat_artist_norm = re.sub(r'\s+', ' ', feat_artist_norm).strip()
            logging.debug(f"  -> Parenthesis: Keeping 'feat' token with normalized artist: 'feat {feat_artist_norm}'")
            return f' feat {feat_artist_norm} '

        if parenthetical_strip_regex and parenthetical_strip_regex.search(content): # Use passed regex
             logging.debug(f"  -> Parenthesis: Removing suffix/term based on strip_keywords: '{content}'")
             return ''

        logging.debug(f"  -> Parenthesis: Removing generic content (not live, feat, or strip keyword).")
        return ''
    
    s_for_matching = re.sub(r'\(([^)]*)\)', process_parenthetical_content, s_for_matching)
    logging.debug(f"Norm Step 4b (After Parenthesis): -> '{s_for_matching}'")

    s_for_matching = ''.join(c for c in s_for_matching if c.isalnum() or c.isspace())
    s_for_matching = re.sub(r'\s+', ' ', s_for_matching).strip()
    logging.debug(f"Norm Step 5 (Final Cleanup): -> '{s_for_matching}' | LiveDetected (from original string): {is_live_format}")

    return s_for_matching, is_live_format

def normalize_string_for_matching(s, parenthetical_strip_regex=None): # Added regex as param
    """Just returns the normalized string part for general matching."""
    stripped_s, _ = normalize_and_detect_specific_live_format(s, parenthetical_strip_regex) # Pass it on
    return stripped_s

def check_album_for_live_indicators(album_title_str, live_keywords_regex, parenthetical_strip_regex=None): # Added regex as param
    """ Checks album title using standard normalization and regex/specific format. """
    if not isinstance(album_title_str, str) or not album_title_str:
        return False

    # Pass parenthetical_strip_regex to the normalization function it calls
    normalized_album_for_check, album_has_specific_live_format = normalize_and_detect_specific_live_format(album_title_str, parenthetical_strip_regex)

    if live_keywords_regex and live_keywords_regex.search(normalized_album_for_check):
        logging.debug(f"Album '{album_title_str}' (normalized: '{normalized_album_for_check}') matched live indicator regex.")
        return True

    if album_has_specific_live_format:
        logging.debug(f"Album '{album_title_str}' detected specific '(live)' format during normalization.")
        return True

    return False