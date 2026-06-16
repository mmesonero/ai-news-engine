"""One-off local -> cloud data transfer (deduped by URL, non-destructive).

  dump <file>   read the DB in DATABASE_URL, write non-noise stories to JSON
  load <file>   read JSON, insert into the DB in DATABASE_URL, skipping any
                cluster whose representative URL already exists (no wipe, no dups)

`load` runs inside a GitHub Action where DATABASE_URL = the Neon secret, so the
cloud credentials never leave GitHub. New rows get fresh IDs (no collisions).
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models.cluster import ClusterItem, ContentCluster
from app.models.embedding import Embedding
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.models.source import Source
from app.repositories.raw_content_repo import RawContentRepository


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


async def dump(path: str) -> None:
    async with SessionLocal() as s:
        sources = {row.id: row for row in (await s.execute(select(Source))).scalars()}
        clusters = (await s.execute(select(ContentCluster))).scalars().all()
        out = []
        for c in clusters:
            members = (
                await s.execute(
                    select(RawContent, ProcessedContent, Embedding)
                    .join(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
                    .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
                    .outerjoin(Embedding, Embedding.raw_content_id == RawContent.id)
                    .where(ClusterItem.cluster_id == c.id)
                )
            ).all()
            if not members:
                continue
            # Skip clusters whose representative is noise / unclassified.
            rep_url = None
            items = []
            any_valuable = False
            for raw, proc, emb in members:
                src = sources.get(raw.source_id)
                is_rep = raw.id == c.representative_content_id
                if is_rep:
                    rep_url = raw.url
                pj = None
                if proc is not None:
                    if not proc.is_noise and proc.theme and proc.theme != "irrelevante":
                        any_valuable = True
                    pj = {
                        "theme": proc.theme, "importance_tier": proc.importance_tier,
                        "importance_score": proc.importance_score, "novelty_score": proc.novelty_score,
                        "business_impact_score": proc.business_impact_score,
                        "linkedin_potential_score": proc.linkedin_potential_score,
                        "cleaned_summary": proc.cleaned_summary, "key_topics": proc.key_topics,
                        "is_noise": proc.is_noise, "rejected_reason": proc.rejected_reason,
                        "ai_generated_insights": proc.ai_generated_insights,
                        "linkedin_angles": proc.linkedin_angles,
                    }
                items.append({
                    "is_rep": is_rep,
                    "source": {"name": src.name, "type": src.type, "url": src.url,
                               "group_name": src.group_name, "config_json": src.config_json} if src else None,
                    "external_id": raw.external_id, "title": raw.title, "url": raw.url,
                    "author": raw.author, "raw_text": raw.raw_text or "",
                    "published_at": _iso(raw.published_at), "fetched_at": _iso(raw.fetched_at),
                    "content_hash": raw.content_hash, "language": raw.language,
                    "embedding_pruned": raw.embedding_pruned,
                    "embedding": [float(x) for x in emb.embedding] if emb is not None else None,
                    "embedding_model": emb.model if emb is not None else None,
                    "processed": pj,
                })
            if not any_valuable or rep_url is None:
                continue
            out.append({"topic": c.cluster_topic, "notified_at": _iso(c.notified_at),
                        "representative_url": rep_url, "items": items})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"dumped {len(out)} clusters -> {path}")


async def load(path: str) -> None:
    from datetime import datetime

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    inserted_clusters = skipped = inserted_items = 0
    async with SessionLocal() as s:
        repo = RawContentRepository(s)
        # source cache by url
        src_by_url = {row.url: row for row in (await s.execute(select(Source))).scalars()}

        async def ensure_source(sj: dict) -> int | None:
            if not sj:
                return None
            existing = src_by_url.get(sj["url"])
            if existing:
                return existing.id
            row = Source(name=sj["name"], type=sj["type"], url=sj["url"],
                         active=True, config_json=sj.get("config_json") or {},
                         group_name=sj.get("group_name"))
            s.add(row)
            await s.flush()
            src_by_url[sj["url"]] = row
            return row.id

        for cl in data:
            # dedup: skip whole cluster if its representative URL already in target
            exists = await s.execute(
                select(RawContent.id).where(RawContent.url == cl["representative_url"])
            )
            if exists.first() is not None:
                skipped += 1
                continue

            new_ids: list[tuple[int, dict]] = []
            rep_new_id = None
            for it in cl["items"]:
                sid = await ensure_source(it["source"])
                if sid is None:
                    continue
                pub = datetime.fromisoformat(it["published_at"]) if it["published_at"] else None
                raw = await repo.upsert(
                    source_id=sid, external_id=it.get("external_id"), title=it["title"],
                    url=it["url"], author=it.get("author"), raw_text=it.get("raw_text") or "",
                    published_at=pub, content_hash=it["content_hash"],
                    language=it.get("language"), metadata={},
                )
                if raw is None:  # url already exists -> skip this item
                    continue
                if it.get("embedding_pruned"):
                    raw.embedding_pruned = True
                await s.flush()
                new_ids.append((raw.id, it))
                if it["is_rep"]:
                    rep_new_id = raw.id
                if it.get("embedding"):
                    s.add(Embedding(raw_content_id=raw.id, embedding=it["embedding"],
                                    model=it.get("embedding_model") or "text-embedding-3-small"))
                if it.get("processed"):
                    p = it["processed"]
                    s.add(ProcessedContent(
                        raw_content_id=raw.id, cleaned_summary=p.get("cleaned_summary"),
                        key_topics=p.get("key_topics") or [], novelty_score=p.get("novelty_score"),
                        importance_score=p.get("importance_score"),
                        linkedin_potential_score=p.get("linkedin_potential_score"),
                        business_impact_score=p.get("business_impact_score"),
                        ai_generated_insights=p.get("ai_generated_insights") or {},
                        linkedin_angles=p.get("linkedin_angles") or {},
                        rejected_reason=p.get("rejected_reason"), is_noise=bool(p.get("is_noise")),
                        theme=p.get("theme"), importance_tier=p.get("importance_tier"),
                    ))
                inserted_items += 1
            if not new_ids:
                continue
            if rep_new_id is None:
                rep_new_id = new_ids[0][0]
            notified = datetime.fromisoformat(cl["notified_at"]) if cl.get("notified_at") else None
            cluster = ContentCluster(cluster_topic=cl.get("topic"),
                                     representative_content_id=rep_new_id, notified_at=notified)
            s.add(cluster)
            await s.flush()
            for rid, _it in new_ids:
                s.add(ClusterItem(cluster_id=cluster.id, raw_content_id=rid, similarity_score=1.0))
            inserted_clusters += 1
            await s.commit()
    print(f"loaded: {inserted_clusters} new clusters, {inserted_items} items; skipped {skipped} existing")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    fpath = sys.argv[2] if len(sys.argv) > 2 else "stories_dump.json"
    if mode == "dump":
        asyncio.run(dump(fpath))
    elif mode == "load":
        asyncio.run(load(fpath))
    else:
        print("usage: db_transfer.py dump|load <file>")
        sys.exit(1)
