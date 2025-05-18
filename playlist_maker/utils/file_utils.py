# playlist_maker/utils/file_utils.py
import re
import os # For os.path.splitext
import logging
from datetime import datetime # Explicitly import if used directly, or ensure 'now' is datetime obj

# (Content of format_output_filename function as it is in your playlist_maker.py)
# ...
def format_output_filename(format_string, raw_basename, now: datetime, default_extension=".m3u"):
    """
    Formats the output filename based on a format string, raw basename, and current time.
    """
    if format_string is None: # Use default logic if no format string is provided
        sanitized_base = re.sub(r'[^a-zA-Z0-9]+', '_', raw_basename).strip('_')
        date_str = now.strftime("%Y-%m-%d")
        filename_stem = f"{sanitized_base}_{date_str}" if sanitized_base else f"playlist_{date_str}"
        return f"{filename_stem}{default_extension}"

    # --- Helper for {basename:transforms} ---
    def process_basename(current_basename, transform_codes_str):
        processed_name = current_basename
        transformed_separator = False

        if 'p' in transform_codes_str:
            processed_name = re.sub(r'[-_.]+', ' ', processed_name)
            processed_name = re.sub(r'\s+', ' ', processed_name).strip()
            transformed_separator = True
        elif 's' in transform_codes_str and not transformed_separator:
            processed_name = re.sub(r'[\s_.]+', '-', processed_name)
            processed_name = re.sub(r'-+', '-', processed_name).strip('-')
            transformed_separator = True
        elif '_' in transform_codes_str and not transformed_separator:
            processed_name = re.sub(r'[\s-.]+', '_', processed_name)
            processed_name = re.sub(r'_+', '_', processed_name).strip('_')
            transformed_separator = True
        
        transformed_case = False
        if 'c' in transform_codes_str:
            processed_name = ' '.join(word.capitalize() for word in processed_name.split(' ') if word)
            transformed_case = True
        elif 'u' in transform_codes_str and not transformed_case:
            processed_name = processed_name.upper()
            transformed_case = True
        elif 'l' in transform_codes_str and not transformed_case:
            processed_name = processed_name.lower()
            transformed_case = True
            
        return processed_name

    final_filename_str = format_string

    def basename_replacer(match):
        transform_codes = match.group(1) 
        return process_basename(raw_basename, transform_codes)
    
    final_filename_str = re.sub(r'\{basename:?([culps_]*)\}', basename_replacer, final_filename_str)

    dt_replacements = {
        'YYYY': now.strftime("%Y"), 'YY': now.strftime("%y"),
        'MM': now.strftime("%m"), 'DD': now.strftime("%d"),
        'hh': now.strftime("%H"), 'mm': now.strftime("%M"),
        'ss': now.strftime("%S"),
    }
    for key, value in dt_replacements.items():
        final_filename_str = final_filename_str.replace(f"{{{key}}}", value)

    name_part, current_extension = os.path.splitext(final_filename_str)
    
    if not current_extension.strip() or current_extension.strip() == ".":
        current_extension = default_extension
    
    invalid_fs_chars_regex = r'[\\/:*?"<>|\x00-\x1F\x7F]'
    sanitized_name_part = re.sub(invalid_fs_chars_regex, '_', name_part)
    sanitized_name_part = re.sub(r'_+', '_', sanitized_name_part)
    sanitized_name_part = sanitized_name_part.strip('_. ')

    if not sanitized_name_part:
        logging.warning(
            f"Generated filename format ('{format_string}') for basename ('{raw_basename}') "
            f"resulted in an empty/invalid stem ('{name_part}' -> '{sanitized_name_part}'). Falling back to default naming."
        )
        sanitized_base_fallback = re.sub(r'[^a-zA-Z0-9]+', '_', raw_basename).strip('_')
        date_str_fallback = now.strftime("%Y-%m-%d")
        filename_stem_fallback = f"{sanitized_base_fallback}_{date_str_fallback}" if sanitized_base_fallback else f"playlist_{date_str_fallback}"
        return f"{filename_stem_fallback}{default_extension}"

    return f"{sanitized_name_part}{current_extension}"