#!/usr/bin/env python3
"""Download a YouTube video's audio as a high-quality 432 Hz MP3.

Usage:
    source .venv-youtube-432/bin/activate
    python downloader_combiner.py "https://www.youtube.com/watch?v=..."

Playlist, Mix, and radio query params are ignored; only the video id is downloaded.
Only download media you own or have permission to use.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

try:
    import yt_dlp
except ModuleNotFoundError:
    yt_dlp = None

try:
    import imageio_ffmpeg
except ModuleNotFoundError:
    imageio_ffmpeg = None


PITCH_RATIO = 432 / 440
OUTPUT_DIR = Path(__file__).resolve().parent / "downloads"
VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")
YOUTUBE_FORMAT = (
    "bestaudio[protocol^=http]/bestaudio[protocol=m3u8_native]/"
    "bestaudio/best[protocol^=http]/best[protocol=m3u8_native]/best"
)
YOUTUBE_DOWNLOAD_PROFILES = [
    {
        "name": "default clients with current player JS",
        "extractor_args": {"youtube": {"player_js_version": ["actual"]}},
    },
    {
        "name": "yt-dlp current default",
        "extractor_args": {},
    },
    {
        "name": "web safari with current player JS",
        "extractor_args": {
            "youtube": {
                "player_client": ["web_safari"],
                "player_js_version": ["actual"],
            }
        },
    },
    {
        "name": "TV embedded fallback",
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_embedded"],
                "player_js_version": ["actual"],
            }
        },
    },
    {
        "name": "iOS fallback",
        "extractor_args": {
            "youtube": {
                "player_client": ["ios"],
                "player_js_version": ["actual"],
            }
        },
    },
    {
        "name": "Android fallback",
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
                "player_js_version": ["actual"],
            }
        },
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download one YouTube link as a 320 kbps MP3 tuned to 432 Hz."
    )
    parser.add_argument("youtube_link", help="YouTube video URL")
    return parser.parse_args()


def _youtube_host(host: str) -> bool:
    host = host.lower().split(":")[0]
    return (
        host == "youtu.be"
        or host.endswith(".youtu.be")
        or host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtube-nocookie.com"
        or host.endswith(".youtube-nocookie.com")
    )


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not _youtube_host(parsed.netloc):
        return None

    host = parsed.netloc.lower().split(":")[0]
    path_parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)

    if host == "youtu.be" or host.endswith(".youtu.be"):
        video_id = path_parts[0] if path_parts else ""
        return video_id if VIDEO_ID_RE.fullmatch(video_id) else None

    video_id = (query.get("v") or [""])[0]
    if VIDEO_ID_RE.fullmatch(video_id):
        return video_id

    if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live", "v"}:
        video_id = path_parts[1]
        if VIDEO_ID_RE.fullmatch(video_id):
            return video_id

    return None


def validate_youtube_url(url: str) -> None:
    if extract_video_id(url) is None:
        raise ValueError("Please provide a valid YouTube URL.")


def normalize_youtube_url(url: str) -> str:
    video_id = extract_video_id(url)
    if video_id is None:
        raise ValueError("Please provide a valid YouTube URL.")
    return f"https://www.youtube.com/watch?{urlencode({'v': video_id})}"


def require_dependencies() -> None:
    missing = []

    if yt_dlp is None:
        missing.append("yt-dlp Python package: python -m pip install yt-dlp")

    if ffmpeg_executable() is None:
        missing.append(
            "ffmpeg executable or imageio-ffmpeg package: "
            "python -m pip install imageio-ffmpeg"
        )

    if missing:
        raise RuntimeError(
            "Missing required dependency:\n  - " + "\n  - ".join(missing)
        )


def ffmpeg_executable() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    if imageio_ffmpeg is None:
        return None

    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def configure_macos_ssl() -> Path | None:
    """Point OpenSSL at macOS keychain CAs so Homebrew Python can reach YouTube."""
    if sys.platform != "darwin":
        return None

    cache_dir = Path.home() / ".cache" / "youtube-432"
    cache_dir.mkdir(parents=True, exist_ok=True)
    bundle = cache_dir / "macos-ca-bundle.pem"

    keychains = [
        Path("/System/Library/Keychains/SystemRootCertificates.keychain"),
        Path("/Library/Keychains/System.keychain"),
        Path.home() / "Library/Keychains/login.keychain-db",
    ]

    chunks: list[str] = []
    for keychain in keychains:
        if not keychain.exists():
            continue
        result = subprocess.run(
            ["security", "find-certificate", "-a", "-p", str(keychain)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            chunks.append(result.stdout.strip())

    if not chunks:
        return None

    bundle.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    os.environ["SSL_CERT_FILE"] = str(bundle)
    os.environ["REQUESTS_CA_BUNDLE"] = str(bundle)
    os.environ["CURL_CA_BUNDLE"] = str(bundle)
    return bundle


def js_runtime_options() -> dict | None:
    deno = shutil.which("deno")
    if deno:
        return {"deno": {"path": deno}}

    node = shutil.which("node")
    if node:
        return {"node": {"path": node}}

    quickjs = shutil.which("qjs")
    if quickjs:
        return {"quickjs": {"path": quickjs}}

    return None


def safe_filename(title: str, video_id: str | None) -> str:
    base = re.sub(r'[\\/:*?"<>|]+', "_", title)
    base = re.sub(r"\s+", " ", base).strip(" ._")
    base = base[:180].strip(" ._") or "youtube_audio"

    if video_id:
        return f"{base} [{video_id}].mp3"

    return f"{base}.mp3"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for number in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find an available filename for {path.name!r}.")


def download_with_options(url: str, temp_dir: Path, options: dict) -> tuple[Path, dict]:
    output_template = str(temp_dir / "%(title).200B [%(id)s].%(ext)s")
    runtime_options = js_runtime_options()
    download_options = {
        **options,
        "noplaylist": True,
        "outtmpl": output_template,
        "quiet": False,
        "no_warnings": False,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "compat_opts": {"no-certifi"},
        "windowsfilenames": True,
    }

    if runtime_options:
        download_options["js_runtimes"] = runtime_options

    with yt_dlp.YoutubeDL(download_options) as downloader:
        info = downloader.extract_info(url, download=True)

        if "entries" in info:
            info = next((entry for entry in info["entries"] if entry), None)
            if info is None:
                raise RuntimeError("The link resolved to an empty playlist instead of a video.")

        for download in info.get("requested_downloads") or []:
            downloaded_path = download.get("filepath") or download.get("_filename")
            if downloaded_path and Path(downloaded_path).exists():
                return Path(downloaded_path), info

        prepared_path = Path(downloader.prepare_filename(info))
        if prepared_path.exists():
            return prepared_path, info

    candidates = [path for path in temp_dir.iterdir() if path.is_file()]
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime), info

    raise RuntimeError("yt-dlp finished, but no downloaded audio file was found.")


def download_best_audio(url: str, temp_dir: Path) -> tuple[Path, dict]:
    errors = []

    for index, profile in enumerate(YOUTUBE_DOWNLOAD_PROFILES, start=1):
        attempt_dir = temp_dir / f"attempt_{index}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        options = {
            "format": YOUTUBE_FORMAT,
            "extractor_args": profile["extractor_args"],
        }

        print(f"Trying download profile: {profile['name']}")
        try:
            return download_with_options(url, attempt_dir, options)
        except Exception as error:
            errors.append(f"{profile['name']}: {error}")
            print(f"Profile failed: {profile['name']}: {error}", file=sys.stderr)

    raise RuntimeError(
        "All YouTube download profiles failed:\n  - " + "\n  - ".join(errors)
    )


def run_command(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def source_sample_rate(source_path: Path, ffmpeg_path: str) -> int:
    if shutil.which("ffprobe") is None:
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-i",
            str(source_path),
        ]
        result = run_command(command, check=False)
        probe_text = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"Audio:.*?(\d+)\s+Hz", probe_text)
        if match:
            return int(match.group(1))

        return 44100

    command = [
        shutil.which("ffprobe") or "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(source_path),
    ]

    try:
        result = run_command(command)
        return int(result.stdout.strip().splitlines()[0])
    except (subprocess.CalledProcessError, IndexError, ValueError):
        return 44100


def ffmpeg_has_filter(filter_name: str, ffmpeg_path: str) -> bool:
    try:
        result = run_command([ffmpeg_path, "-hide_banner", "-filters"])
    except subprocess.CalledProcessError:
        return False

    pattern = re.compile(rf"^\s*[TSC\.]{{3}}\s+{re.escape(filter_name)}\s", re.MULTILINE)
    return bool(pattern.search(result.stdout))


def pitch_filter(source_path: Path, ffmpeg_path: str) -> tuple[str, int]:
    sample_rate = source_sample_rate(source_path, ffmpeg_path)

    if ffmpeg_has_filter("rubberband", ffmpeg_path):
        return f"rubberband=pitch={PITCH_RATIO:.12f}", sample_rate

    tuned_sample_rate = round(sample_rate * PITCH_RATIO)
    tempo_ratio = sample_rate / tuned_sample_rate
    return (
        f"asetrate={tuned_sample_rate},aresample={sample_rate},atempo={tempo_ratio:.12f}",
        sample_rate,
    )


def convert_to_432_mp3(source_path: Path, output_path: Path) -> None:
    ffmpeg_path = ffmpeg_executable()
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is not available.")

    audio_filter, sample_rate = pitch_filter(source_path, ffmpeg_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-af",
        audio_filter,
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        "-ar",
        str(sample_rate),
        "-map_metadata",
        "0",
        "-id3v2_version",
        "3",
        str(output_path),
    ]

    try:
        run_command(command)
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()
        raise RuntimeError(f"ffmpeg conversion failed:\n{details}") from error


def main() -> int:
    args = parse_args()

    try:
        validate_youtube_url(args.youtube_link)
        require_dependencies()
        configure_macos_ssl()
        download_url = normalize_youtube_url(args.youtube_link)
        if download_url != args.youtube_link:
            print(f"Using video URL: {download_url}")

        with tempfile.TemporaryDirectory(prefix="youtube_audio_") as temp_root:
            temp_dir = Path(temp_root)
            source_path, info = download_best_audio(download_url, temp_dir)
            final_name = safe_filename(
                info.get("title") or source_path.stem,
                info.get("id"),
            )
            output_path = unique_path(OUTPUT_DIR / final_name)
            convert_to_432_mp3(source_path, output_path)

        print(f"Saved MP3: {output_path}")
        return 0
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
