# Getting material in

Pass `winnow ingest` a URL and it fetches the captions for you:

```bash
winnow ingest https://youtu.be/SOME_VIDEO
```

Pass it a file or a folder instead and it uses that, untouched. Both work; the rest of this
page covers what the first one actually does, and how to do it yourself when you want more
control than one command gives you.

## What Winnow accepts

| you have | what to pass | notes |
|---|---|---|
| a video URL | `winnow ingest https://youtu.be/...` | fetches captions with yt-dlp, caches them per URL |
| a transcript file | `winnow ingest talk.txt` | plain text or markdown |
| a subtitle file | `winnow ingest talk.en.vtt` | `.vtt`, `.srt`, `.ass`, `.sub` |
| a folder | `winnow ingest ./talk/` | finds `transcript.txt` or any subtitle file inside |
| a media file plus a transcript beside it | `winnow ingest ./talk/` | media is used only for frames |

**Two things Winnow will not do.** It does not transcribe: a video with no captions is a
stop with instructions, not a silent empty result — see
[Producing a transcript](#producing-a-transcript). And it does not read PDFs; convert them
first with something like `pdftotext` and pass the text.

## How fetching works, and where the decisions stay yours

Winnow shells out to [yt-dlp](https://github.com/yt-dlp/yt-dlp). Three deliberate limits:

1. **You install yt-dlp; Winnow never installs it for you.** `pip install -U yt-dlp`. If it
   is absent, Winnow stops and says so rather than reaching for your package manager. There
   is a test asserting no install is attempted, because a message promising restraint is not
   the same as restraint.
2. **The exact command is printed before it runs.** Nothing reaches the network without
   appearing on your screen first, so you can see precisely what was requested and from
   where.
3. **Captions only, unless you ask otherwise.** `--with-video` downloads the video, capped
   at 720p, and is needed only by packs that describe frames. Captions are a small text file;
   the video is hundreds of megabytes and buys nothing else, since frames are downscaled to
   640px before the vision model sees them.

Fetched material is cached under `cache_path`, one folder per URL, named after the link. The
same URL is not fetched twice, and you can look inside and see exactly what arrived.
`--refetch` ignores the cache.

### Whether you should fetch at all is still your call

Winnow runs the command; it does not decide that running it is appropriate. Whether you may
download from a particular site depends on that site's terms, the content's licence, your
jurisdiction and your purpose. Many sites prohibit it, some permit it for personal use, and
none of this is legal advice. You choose the URL, you installed the downloader, and you see
the command before it runs — the judgement is yours, and Winnow is deliberately built so
that it cannot be made silently on your behalf.

## Driving yt-dlp yourself

Everything below is for when one command is not enough: playlists, channels, awkward
formats, or simply wanting the files before Winnow sees them. Fetch into a folder, then
`winnow ingest ./that-folder/`.

### Installing

```bash
pip install -U yt-dlp
```

Keep it updated. Streaming sites change their internals frequently and an out-of-date yt-dlp
fails in confusing ways — an unexplained extraction error is usually a stale version.

### Captions only — the recommended path

```bash
yt-dlp --skip-download --write-auto-subs --write-subs \
       --sub-langs "en.*" --sub-format vtt \
       -o "%(id)s/%(id)s.%(ext)s" \
       "<URL>"
```

What each flag does:

- `--skip-download` — do not fetch the media at all. Fast, small, and usually sufficient.
- `--write-subs` — human-authored subtitles, when they exist. Better quality.
- `--write-auto-subs` — automatic (machine) captions. Nearly always present.
- `--sub-langs "en.*"` — English variants. Use your own language code as needed.
- `--sub-format vtt` — WebVTT. Winnow also reads SRT.
- `-o "%(id)s/%(id)s.%(ext)s"` — one folder per item, which is the layout `winnow ingest`
  expects when you pass a folder.

Then:

```bash
winnow ingest ./<id>/
```

### With video, when you want frame description

Some material carries its substance on screen rather than in speech — benchmark tables,
terminal output, architecture diagrams. For those, the vision model needs actual frames:

```bash
yt-dlp -f "bv*[height<=720]+ba/b[height<=720]" \
       --write-auto-subs --write-subs --sub-langs "en.*" --sub-format vtt \
       -o "%(id)s/%(id)s.%(ext)s" \
       "<URL>"
```

`-f "bv*[height<=720]+ba/b[height<=720]"` caps the resolution at 720p. Higher resolutions
cost download time and disk for no benefit: frames are downscaled to 640px wide before the
vision model ever sees them.

### Playlists and channels

```bash
# Look before you leap: list without downloading anything.
yt-dlp --flat-playlist --print "%(id)s | %(duration)s | %(title)s" "<PLAYLIST URL>"
```

Always list first. A channel can hold thousands of items, most of which restate each other,
and the whole purpose of Winnow is to avoid processing material you already know. Skim the
titles, choose a sample that covers genuinely different ground, and fetch only those.

```bash
# A specific range, once you know what is there.
yt-dlp --playlist-items 1-20 --skip-download --write-auto-subs \
       --sub-langs "en.*" --sub-format vtt -o "%(id)s/%(id)s.%(ext)s" "<URL>"
```

### When it fails

- **HTTP 403 or 429** — throttling, not a permanent failure. Wait, then retry. Add
  `--sleep-requests 2` for bulk fetches to avoid triggering it in the first place.
- **"Unable to extract"** — usually an out-of-date yt-dlp. `pip install -U yt-dlp` first,
  before investigating anything else.
- **No subtitles written** — the item genuinely has none. See below.
- **Sign-in required** — some content is gated. Winnow has nothing to say about this; if you
  choose to authenticate, that is between you and the site.

## Producing a transcript

When captions do not exist, you need speech-to-text. Winnow does not do this, but
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) runs locally and well:

```bash
pip install faster-whisper
```

```python
from faster_whisper import WhisperModel

model = WhisperModel("base.en", device="cpu", compute_type="int8")
segments, _ = model.transcribe("talk/talk.mp4")
with open("talk/transcript.txt", "w", encoding="utf-8") as f:
    f.write(" ".join(s.text.strip() for s in segments))
```

Then `winnow ingest ./talk/`. Larger models (`small.en`, `medium.en`) transcribe better and
more slowly; `base.en` is usually enough, since extraction cares about content rather than
perfect wording.

## ffmpeg

Only needed for frame extraction. If you are working from transcripts alone, skip it.

- **Windows**: `winget install --id Gyan.FFmpeg -e`
  **Then open a new terminal.** The existing one does not see the updated PATH, and
  `ffmpeg: not found` immediately after a successful install almost always means this rather
  than a failed installation.
- **macOS**: `brew install ffmpeg`
- **Debian/Ubuntu**: `sudo apt install ffmpeg`

Verify with `ffmpeg -version`.

## Other sources

Nothing about Winnow is specific to any one site:

- **Podcasts** — many publish transcripts; otherwise use faster-whisper on the audio file.
- **Conference talks** — often carry official captions; download or copy them.
- **Recorded meetings** — most conferencing tools export a transcript directly.
- **Papers and documentation** — markdown and text work directly. PDFs do not: convert
  them with `pdftotext` first and pass the result.
- **Your own recordings** — a file on disk is a file on disk.
