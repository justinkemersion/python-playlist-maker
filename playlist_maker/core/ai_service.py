# playlist_maker/core/ai_service.py
import os
import json
import logging
# Ensure you have `pip install openai` and add it to requirements.txt
try:
    from openai import OpenAI, APIError, APITimeoutError, RateLimitError
except ImportError:
    OpenAI = None # Allows script to load if openai is not installed, but AI features will fail.
    APIError = APITimeoutError = RateLimitError = Exception # Dummy exceptions

class AIService:
    def __init__(self, api_key: str | None, default_model: str):
        self.client = None
        self.default_model = default_model
        
        if OpenAI is None:
            msg = "OpenAI library not installed. AI features are unavailable. Please run 'pip install openai'."
            logging.error(f"AI_SVC: {msg}")
            raise ImportError(msg) # Make it a hard stop if AI is expected

        effective_api_key = api_key
        if not effective_api_key:
            effective_api_key = os.environ.get("OPENAI_API_KEY")
        
        if not effective_api_key:
            logging.warning("AI_SVC: OpenAI API key not provided (checked config/args and OPENAI_API_KEY env var). "
                          "AI features will be disabled.")
            return # Client remains None
        
        try:
            self.client = OpenAI(api_key=effective_api_key)
            logging.info("AI_SVC: OpenAI client initialized successfully.")
        except Exception as e:
            logging.error(f"AI_SVC: Failed to initialize OpenAI client: {e}", exc_info=True)
            self.client = None # Ensure client is None on failure

    def generate_playlist_from_prompt(self, prompt: str, model_override: str | None) -> list[tuple[str, str]]:
        """
        Sends a prompt to the AI and expects a list of (Artist, Song) tuples.
        Uses OpenAI's chat completions with a tool for structured JSON output.
        """
        if not self.client:
            logging.error("AI_SVC: OpenAI client not initialized (missing API key or library). Cannot generate playlist.")
            raise ConnectionError("AI client not initialized. Check API key and ensure 'openai' library is installed.")

        target_model = model_override if model_override else self.default_model
        logging.info(f"AI_SVC: Requesting playlist from model '{target_model}' with prompt: '{prompt}'")

        # Define the tool schema for creating a playlist
        playlist_tool_schema = {
            "type": "function",
            "function": {
                "name": "create_song_playlist",
                "description": "Creates a playlist of songs, each with an artist and song title.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "playlist": {
                            "type": "array",
                            "description": "A list of songs, each item an object with 'artist' and 'song' properties.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "artist": {"type": "string", "description": "The name of the artist performing the song."},
                                    "song": {"type": "string", "description": "The title of the song."}
                                },
                                "required": ["artist", "song"]
                            }
                        }
                    },
                    "required": ["playlist"]
                }
            }
        }

        try:
            messages = [
                {"role": "system", "content": "You are a helpful playlist assistant. Your task is to generate a list of songs based on the user's prompt. Please use the provided 'create_song_playlist' tool to format your response as a structured playlist."},
                {"role": "user", "content": prompt}
            ]
            
            response = self.client.chat.completions.create(
                model=target_model,
                messages=messages,
                tools=[playlist_tool_schema],
                tool_choice={"type": "function", "function": {"name": "create_song_playlist"}} # Force use of the tool
            )

            message = response.choices[0].message
            tool_calls = message.tool_calls

            if tool_calls and tool_calls[0].function.name == "create_song_playlist":
                try:
                    playlist_json_str = tool_calls[0].function.arguments
                    playlist_data = json.loads(playlist_json_str) # Should be {"playlist": [{"artist": "...", "song": "..."}, ...]}
                except json.JSONDecodeError as jde:
                    logging.error(f"AI_SVC: Failed to decode JSON from AI tool arguments: {jde}. Arguments: '{playlist_json_str}'")
                    return [] # Or raise a more specific error

                tracks = []
                for item in playlist_data.get("playlist", []):
                    artist = item.get("artist")
                    song = item.get("song") # Changed from 'title' to 'song' to match your schema
                    if artist and song:
                        tracks.append((str(artist).strip(), str(song).strip())) # Ensure strings
                    else:
                        logging.warning(f"AI_SVC: Received incomplete track item from AI: {item}")
                
                if not tracks:
                    logging.warning(f"AI_SVC: AI returned an empty playlist or malformed data for prompt: '{prompt}'. Data: {playlist_data}")
                return tracks
            else:
                # Log the raw content if the tool wasn't used, in case there's useful text.
                raw_content = message.content if hasattr(message, 'content') else "No raw content."
                logging.error(f"AI_SVC: AI did not use the 'create_song_playlist' tool as expected. Raw content: '{raw_content}'. Full response: {response.model_dump_json(indent=2)}")
                return []

        except APIError as e: # Catch specific OpenAI errors
            logging.error(f"AI_SVC: OpenAI API Error (model: '{target_model}'): {e}", exc_info=True)
            raise ConnectionError(f"AI API Error: {e.type if hasattr(e, 'type') else 'Unknown'} - {e.message if hasattr(e, 'message') else str(e)}")
        except APITimeoutError as e:
            logging.error(f"AI_SVC: OpenAI API Timeout (model: '{target_model}'): {e}", exc_info=True)
            raise ConnectionError(f"AI API request timed out.")
        except RateLimitError as e:
            logging.error(f"AI_SVC: OpenAI API Rate Limit Exceeded (model: '{target_model}'): {e}", exc_info=True)
            raise ConnectionError(f"AI API rate limit exceeded. Please try again later or check your usage.")
        except Exception as e: # Catch any other general exception during API call
            logging.error(f"AI_SVC: General error during API call to '{target_model}': {e}", exc_info=True)
            raise ConnectionError(f"AI API call failed unexpectedly: {e}")