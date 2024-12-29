from flask import Flask, request, jsonify, send_file, render_template
import requests
import logging
from mutagen.mp4 import MP4, MP4Cover
from pathlib import Path  # Added for cross-platform path handling

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

API_URL = "https://jiosaavn-ts.vercel.app"

def fetch_lyrics(song_id):
    """Fetch lyrics from the provided URL."""
    try:
        url = f"https://jiosaavn-ts.vercel.app/get/lyrics?id={song_id}"
        response = requests.get(url)
        response.raise_for_status()
        lyrics_data = response.json()

        if lyrics_data.get("status") == "Success" and lyrics_data["data"]:
            return lyrics_data["data"].get("lyrics")

        logger.warning("Lyrics not available for the song.")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching lyrics: {e}")
        return None


def add_metadata_with_cover(file_path, song_info, song_id):
    """Add metadata including cover art and lyrics to the M4A file."""
    try:
        audio = MP4(file_path)

        # Add title metadata
        audio.tags['\xa9nam'] = [song_info.get('name', 'Unknown')]

        # Add artist metadata
        artists = song_info.get("artist_map", {}).get("artists", [])
        artist = artists[0].get("name", "Unknown") if artists else "Unknown"
        audio.tags['\xa9ART'] = [artist]

        # Add album metadata
        album = song_info.get('album', {})
        album_name = album.get('name', 'Unknown') if isinstance(album, dict) else album
        audio.tags['\xa9alb'] = [album_name]

        # Add cover art metadata
        if song_info.get('image'):
            try:
                image_data = song_info['image']
                if isinstance(image_data, list) and image_data:
                    image_url = image_data[-1].get('link')
                    if image_url:
                        image_response = requests.get(image_url)
                        image_response.raise_for_status()

                        cover_data = MP4Cover(
                            image_response.content,
                            imageformat=MP4Cover.FORMAT_JPEG if image_url.lower().endswith(('.jpg', '.jpeg'))
                            else MP4Cover.FORMAT_PNG
                        )
                        audio.tags['covr'] = [cover_data]
            except Exception as e:
                logger.error(f"Error adding cover art: {e}")

        # Fetch and add lyrics metadata
        lyrics = fetch_lyrics(song_id)
        if lyrics:
            audio.tags['\xa9lyr'] = [lyrics]

        # Save metadata
        audio.save()
        logger.info(f"Metadata added to {file_path}")
        return True

    except Exception as e:
        logger.error(f"Error adding metadata: {e}")
        return False


@app.route('/api/download', methods=['GET'])
def download_song():
    try:
        quality = request.args.get('quality', 'low')
        song_id = request.args.get('id')
        
        if not song_id:
            return jsonify({"error": "Song ID is required"}), 400

        # Fetch song details
        logger.info(f"Fetching song details for ID: {song_id}")
        response = requests.get(f"{API_URL}/song?id={song_id}")
        response.raise_for_status()
        raw_data = response.json()
        
        song_info = raw_data.get('data', {}).get('songs', [])[0]
        logger.info(f"Processing song: {song_info.get('name')}")
        
        # Validate download URLs exist
        download_urls = song_info.get("download_url", [])
        if not download_urls or not isinstance(download_urls, list):
            return jsonify({"error": "No download URLs available"}), 400

        # Select download URL based on quality
        try:
            if quality == 'low' and len(download_urls) > 0:
                download_url = download_urls[1]["link"]
            elif quality == 'medium' and len(download_urls) > 2:
                download_url = download_urls[2]["link"]
            elif quality == 'high' and download_urls:
                download_url = download_urls[-1]["link"]
            else:
                download_url = download_urls[0]["link"]  # Default to first available quality
        except (IndexError, KeyError) as e:
            logger.error(f"Error selecting download URL: {e}")
            return jsonify({"error": "Failed to get download URL for specified quality"}), 400

        song_title = song_info.get("name", "Unknown")
        logger.info(f"Downloading song: {song_title}")

        # Create file path using pathlib for cross-platform compatibility
        tmp_dir = Path('/tmp')
        if not tmp_dir.exists():
            tmp_dir.mkdir(parents=True, exist_ok=True)
            
        file_path = tmp_dir / f"song_{song_id}.m4a"
        logger.info(f"Temporary file path: {file_path}")

        # Fetch and save the audio file
        audio_response = requests.get(download_url, stream=True)
        audio_response.raise_for_status()

        # Write the file
        with open(file_path, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Add metadata
        if not add_metadata_with_cover(str(file_path), song_info, song_id):
            logger.warning("Failed to add metadata to the file")

        try:
            return send_file(
                str(file_path),
                as_attachment=True,
                download_name=f"{song_title}.m4a",
                mimetype="audio/mp4"
            )
        finally:
            # Clean up the file after sending
            try:
                if file_path.exists():
                    file_path.unlink()
            except Exception as e:
                logger.error(f"Error removing temporary file: {e}")

    except requests.exceptions.RequestException as e:
        logger.error(f"API request error: {e}")
        return jsonify({"error": "Failed to fetch data from the API"}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/search', methods=['GET'])
def search_songs():
    try:
        query = request.args.get('query')
        if not query:
            return jsonify({"error": "Query parameter 'query' is required"}), 400
            
        logger.info(f"Searching for: {query}")
        response = requests.get(f"{API_URL}/search?q={query}")
        response.raise_for_status()
        raw_data = response.json()

        results = raw_data.get("data", {}).get("songs", {}).get("data", [])
        
        res_data = {
            "song_data": results,
            "count": len(results)
        }
        return jsonify({"songs": res_data}), 200
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Search API error: {e}")
        return jsonify({"error": "Failed to fetch data from the API"}), 500

@app.route("/", methods=['GET'])
def index():
    return render_template("index.html")

if __name__ == '__main__':
    app.run(debug=True)