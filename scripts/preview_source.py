"""Preview what an ingestor would extract from a single source.

No database, no OpenAI calls. Just runs the ingestor and prints the first N drafts.

Usage:
  python scripts/preview_source.py rss https://hackaday.com/feed/
  python scripts/preview_source.py rss https://techcrunch.com/feed/ --limit 3
  python scripts/preview_source.py html https://example.com \\
      --config '{"link_selector":"a.card","title_selector":"h1","body_selector":"article"}'
  python scripts/preview_source.py youtube @claude
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion import get_ingestor  # noqa: E402
from app.models.source import Source  # noqa: E402


def _fmt_draft(i: int, d) -> str:  # type: ignore[no-untyped-def]
    body = d.raw_text or ""
    snippet = textwrap.shorten(body.replace("\n", " "), width=240, placeholder=" ...")
    return (
        f"\n[{i}] {d.title}\n"
        f"     url:   {d.url}\n"
        f"     ext:   {d.external_id}\n"
        f"     pub:   {d.published_at}\n"
        f"     len:   {len(body)} chars\n"
        f"     body:  {snippet}"
    )


async def _run(args: argparse.Namespace) -> int:
    source = Source(
        name="preview",
        type=args.type,
        url=args.url,
        active=True,
        config_json=json.loads(args.config) if args.config else {},
    )
    ingestor = get_ingestor(args.type)
    print(f"-> fetching {args.type}: {args.url}", file=sys.stderr)
    drafts = await ingestor.fetch(source)
    print(f"<- got {len(drafts)} drafts (showing up to {args.limit})", file=sys.stderr)
    if not drafts:
        print("(no drafts)")
        return 1
    for i, d in enumerate(drafts[: args.limit], start=1):
        print(_fmt_draft(i, d))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("type", choices=["rss", "html", "youtube"])
    parser.add_argument("url", help="feed URL, page URL, UC channel id, or @handle")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--config", help="JSON string for source.config_json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
