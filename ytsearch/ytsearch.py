#!/usr/bin/env python3
"""Search YouTube video transcripts by keyword. Pulls captions directly from YouTube -- no download, no API key.

Usage:
    uv run ytsearch.py <url> <search_terms...>
    uv run ytsearch.py <url>                              # dump full transcript
    uv run ytsearch.py <url> -c 30 <search_terms>         # context window in seconds (default: 15)
    uv run ytsearch.py <url> --json <search_terms>         # JSON output for agents
    uv run ytsearch.py <url> --json                        # full transcript as JSON

Examples:
    uv run ytsearch.py "https://www.youtube.com/watch?v=abc123" "hacking devices"
    uv run ytsearch.py "https://youtu.be/abc123" claude sonos --context 30
    uv run ytsearch.py "https://youtu.be/abc123" --json "reverse engineer"
"""

import argparse
import json
import re
import sys
from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url: str) -> str:
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    sys.exit(f"Could not extract video ID from: {url}")


def fmt_ts(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def yt_url(video_id: str, seconds: float) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={int(seconds)}s"


def get_transcript(video_id: str) -> list[dict]:
    ytt_api = YouTubeTranscriptApi()
    transcript = ytt_api.fetch(video_id, languages=["en"])
    return [{"text": s.text, "start": s.start, "duration": s.duration} for s in transcript.snippets]


def build_clusters(segments: list[dict], terms: list[str], context_sec: float) -> tuple[list[int], list[tuple]]:
    terms_lower = [t.lower() for t in terms]
    matches = []
    for i, seg in enumerate(segments):
        text_lower = seg["text"].lower()
        if any(t in text_lower for t in terms_lower):
            matches.append(i)

    if not matches:
        return [], []

    clusters = []
    for idx in matches:
        seg = segments[idx]
        start = seg["start"]
        end = start + seg["duration"]
        ctx_start = max(0, start - context_sec)
        ctx_end = end + context_sec
        if clusters and ctx_start <= clusters[-1][1]:
            clusters[-1] = (clusters[-1][0], max(clusters[-1][1], ctx_end))
        else:
            clusters.append((ctx_start, ctx_end))

    return matches, clusters


def search_transcript_json(video_id: str, segments: list[dict], terms: list[str], context_sec: float):
    matches, clusters = build_clusters(segments, terms, context_sec)
    terms_lower = [t.lower() for t in terms]

    if not matches:
        return json.dumps({"query": terms, "matches": 0, "sections": []})

    sections = []
    for c_start, c_end in clusters:
        lines = []
        for seg in segments:
            if seg["start"] + seg["duration"] < c_start:
                continue
            if seg["start"] > c_end:
                break
            lines.append({
                "timestamp": fmt_ts(seg["start"]),
                "start": round(seg["start"], 2),
                "text": seg["text"],
                "match": any(t in seg["text"].lower() for t in terms_lower),
            })
        sections.append({
            "start": fmt_ts(c_start),
            "end": fmt_ts(c_end),
            "url": yt_url(video_id, c_start),
            "lines": lines,
        })

    return json.dumps({
        "video_id": video_id,
        "query": terms,
        "matches": len(matches),
        "sections": sections,
    }, indent=2)


def search_transcript(video_id: str, segments: list[dict], terms: list[str], context_sec: float):
    matches, clusters = build_clusters(segments, terms, context_sec)
    terms_lower = [t.lower() for t in terms]

    if not matches:
        print(f"No matches found for: {' '.join(terms)}")
        return

    print(f"Found {len(matches)} matches in {len(clusters)} section(s):\n")

    for ci, (c_start, c_end) in enumerate(clusters):
        link = yt_url(video_id, c_start)
        print(f"--- Section {ci + 1} [{fmt_ts(c_start)} - {fmt_ts(c_end)}] {link} ---")
        for seg in segments:
            seg_start = seg["start"]
            seg_end = seg_start + seg["duration"]
            if seg_end < c_start:
                continue
            if seg_start > c_end:
                break
            marker = " >> " if any(t in seg["text"].lower() for t in terms_lower) else "    "
            print(f"  [{fmt_ts(seg_start)}]{marker}{seg['text']}")
        print()


def dump_transcript(segments: list[dict], as_json: bool = False):
    if as_json:
        out = [{"timestamp": fmt_ts(s["start"]), "start": round(s["start"], 2), "text": s["text"]} for s in segments]
        print(json.dumps(out, indent=2))
    else:
        for seg in segments:
            print(f"[{fmt_ts(seg['start'])}] {seg['text']}")


def main():
    parser = argparse.ArgumentParser(
        description="Search YouTube video transcripts. No download, no API key.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Pulls captions directly from YouTube's caption endpoint over HTTP.\nNo audio/video download. No API key. No whisper. Just text.",
    )
    parser.add_argument("url", help="YouTube URL or video ID")
    parser.add_argument("terms", nargs="*", help="Search terms (if empty, dumps full transcript)")
    parser.add_argument("-c", "--context", type=float, default=15.0,
                        help="Context window in seconds around matches (default: 15)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON (for piping to other tools or agents)")
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    segments = get_transcript(video_id)

    if not args.terms:
        dump_transcript(segments, as_json=args.json)
    elif args.json:
        print(search_transcript_json(video_id, segments, args.terms, args.context))
    else:
        search_transcript(video_id, segments, args.terms, args.context)


if __name__ == "__main__":
    main()
