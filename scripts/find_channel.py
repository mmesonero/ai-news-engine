"""Resolve a YouTube channel from a sample video, then list its recent uploads."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import feedparser
import httpx

VIDEO_ID = sys.argv[1] if len(sys.argv) > 1 else "S4gsd1_f-Ng"


def main() -> None:
    r = httpx.get(
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        follow_redirects=True,
        cookies={"CONSENT": "YES+1", "SOCS": "CAI"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20.0,
    )
    print(f"status: {r.status_code}  html: {len(r.text)} chars")

    ch_match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', r.text)
    name_match = re.search(r'"ownerChannelName":"([^"]+)"', r.text) or re.search(
        r'"author":"([^"]+)"', r.text
    )
    handle_match = re.search(r'"canonicalBaseUrl":"/(@[^"]+)"', r.text)

    channel_id = ch_match.group(1) if ch_match else None
    channel_name = name_match.group(1) if name_match else None
    handle = handle_match.group(1) if handle_match else None
    print(f"channel_id:   {channel_id}")
    print(f"channel_name: {channel_name}")
    print(f"handle:       {handle}")

    if channel_id is None:
        print("could not resolve channel.")
        return

    feed = feedparser.parse(
        f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    )
    print(f"\nRecent uploads ({len(feed.entries)}):")
    for e in feed.entries[:5]:
        print(f"  - {e.get('published','')[:10]}  {e.title[:80]}")
        print(f"      https://www.youtube.com/watch?v={e.get('yt_videoid','')}")


if __name__ == "__main__":
    main()
