# ytsearch

Search YouTube video transcripts from the terminal. No download, no API key, no whisper.

Pulls captions directly from YouTube's endpoint over HTTP. Instant results with timestamps and deep links.

## Install

```bash
# with uv (recommended)
uvx --from git+https://github.com/infatoshi/ytsearch ytsearch

# or clone and run
git clone https://github.com/infatoshi/ytsearch.git
cd ytsearch
uv run ytsearch.py <url> <terms>
```

## Usage

```bash
# search for keywords -- returns matching sections with timestamps
uv run ytsearch.py "https://www.youtube.com/watch?v=VIDEO_ID" "search term"

# multiple search terms (OR match)
uv run ytsearch.py "https://youtu.be/VIDEO_ID" transformer attention "self-attention"

# adjust context window around matches (default: 15s)
uv run ytsearch.py "https://youtu.be/VIDEO_ID" -c 30 "gradient descent"

# dump full transcript
uv run ytsearch.py "https://youtu.be/VIDEO_ID"

# JSON output (for piping to agents, jq, etc.)
uv run ytsearch.py "https://youtu.be/VIDEO_ID" --json "search term"
```

## Output

Human-readable by default:

```
Found 3 matches in 1 section(s):

--- Section 1 [09:25 - 10:45] https://www.youtube.com/watch?v=VIDEO_ID&t=565s ---
  [09:25]    So in January I went through a period of Claude psychosis.
  [09:29]    So I built a Claude that takes care of my home
  [09:33] >> Dobby the elf. And basically I used the agents to find
  [09:43] >> all the smart home subsystems on the local area network
```

`>>` marks lines containing your search terms. Each section includes a clickable YouTube link at the exact timestamp.

`--json` outputs structured data:

```json
{
  "video_id": "kwSVtQ7dziU",
  "query": ["dobby"],
  "matches": 3,
  "sections": [
    {
      "start": "09:13",
      "end": "11:40",
      "url": "https://www.youtube.com/watch?v=kwSVtQ7dziU&t=553s",
      "lines": [
        {"timestamp": "09:10", "start": 550.12, "text": "...", "match": false},
        {"timestamp": "09:33", "start": 573.44, "text": "Dobby the elf...", "match": true}
      ]
    }
  ]
}
```

## Agent usage

Built for AI coding agents (Claude Code, Codex, Cursor, etc.). Point your agent at a YouTube video and search it:

```bash
# in your CLAUDE.md, .cursorrules, or agent prompt:
# "To search YouTube transcripts: uv run /path/to/ytsearch.py <url> [--json] <terms>"
```

The `--json` flag gives structured output that agents can parse directly. No auth, no tokens, no setup.
