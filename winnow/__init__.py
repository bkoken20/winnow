"""Winnow — give it a YouTube link, and it tells you what in the video you do not know.

Separating grain from chaff. Most of any talk restates things you have already met, so
Winnow fetches the captions, extracts every specific claim, compares them against a corpus
of what you have already watched and read, and shows you the few that are new.

Links are the common case, not the only one: a transcript, a folder, or your own notes work
the same way. What counts as a claim, and what "already known" means, live in a domain pack,
so the tool is not tied to any subject.
"""

__version__ = "0.1.0"
