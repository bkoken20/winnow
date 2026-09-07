# Getting material in

**Winnow does not download anything.** It has no network code for acquisition, no built-in
downloader, and no "just paste a URL" mode. You obtain material yourself, by whatever means
is appropriate for you and lawful where you are, and you point Winnow at the result.

This page explains how, in detail, because leaving you to work it out would be a poor trade
for a boundary the project holds on purpose.

## Why it works this way

Four reasons, in descending order of how much they matter:

1. **It is your call, not ours.** Whether you may download a particular video depends on the
   site's terms, the content's licence, your jurisdiction, and your purpose. A tool that
   downloads on your behalf quietly makes that judgement for you. This one does not.
2. **It keeps the project clean.** Winnow distributes no downloader and performs no
   downloading, so nothing here inherits anyone else's terms of service.
3. **It makes Winnow testable.** The whole pipeline runs offline against files on disk,
   which is why the test suite needs no network and no model server.
4. **It widens what Winnow works on.** Because the input is "a file", Winnow works equally
   on conference recordings, podcast episodes, lecture captures, internal meeting archives,
   a folder of PDFs you already own, or anything else you can turn into text.

## What Winnow accepts

Point `winnow ingest` at any of:

| you have | what to pass | notes |
|---|---|---|
| a transcript file | `winnow ingest talk.txt` | plain text or markdown |
| a subtitle file | `winnow ingest talk.en.vtt` | `.vtt`, `.srt`, `.ass`, `.sub` |
| a folder | `winnow ingest ./talk/` | finds `transcript.txt` or any subtitle file inside |
| a media file plus a transcript beside it | `winnow ingest ./talk/` | media is used only for frames |

If a folder holds media but **no** transcript, Winnow stops and tells you so. It will not
transcribe audio for you — see [Producing a transcript](#producing-a-transcript) below.

## yt-dlp

[yt-dlp](https://github.com/yt-dlp/yt-dlp) is the tool most people use to obtain video and
captions from streaming sites. It is not bundled with Winnow, not invoked by Winnow, and not
required by Winnow — but it is the most likely way you will produce input, so here is how it
works.

### Before you use it

Read the terms of the site you are pointing it at. Many prohibit downloading. Some permit it
for personal use. Some content carries a licence that allows it and some does not. Rules
differ by country, and none of this is legal advice — the point is simply that **the decision
is yours to make deliberately**, which is why this tool does not make it for you.

Note also that on most sites, **you do not need the video at all**. Captions alone are enough
for everything Winnow does except frame description, and captions are a small text file
rather than a several-hundred-megabyte download. Prefer them.

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
- **Papers and documentation** — already text. Convert PDFs with `pdftotext` and pass the
  result.
- **Your own recordings** — a file on disk is a file on disk.
