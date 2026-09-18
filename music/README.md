# Music scripts

Scripts related to audio download and conversion.

## `downloader_combiner.py`

Download a single YouTube video's audio and convert it to a 320 kbps MP3 pitched to 432 Hz.

Only download media you own or have permission to use.

```bash
python -m venv .venv-youtube-432
source .venv-youtube-432/bin/activate
pip install -r requirements.txt
python downloader_combiner.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Output files are written to `downloads/` (not committed).
