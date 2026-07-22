"""Post-clustering LLM judge: merge cluster pairs that semantic dedup missed.

Why: cosine similarity catches near-identical text, but two articles about the
SAME news event with different angles (e.g. "Opus 4.8 launches" vs "Claude is
more honest now") can sit at cosine 0.65-0.80 — below our cluster threshold.

How: for each cluster whose representative is in the "borderline neighbourhood"
of another cluster (cosine between MIN and cluster_threshold), ask the LLM
"same event?". If yes, merge — move all items from the smaller cluster into
the larger one and drop the smaller cluster.

Cost: ~1 OpenAI call per borderline pair. Capped at a small number to avoid
blowing the budget on densely-related corpora.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_client import json_completion
from app.ai.prompts import (
    CLUSTER_GROUPING_V1_SYSTEM,
    CLUSTER_GROUPING_V1_USER,
    INJECTION_GUARD,
    SAME_EVENT_V1_SYSTEM,
    SAME_EVENT_V1_USER,
)
from app.ai.sanitize import neutralize, wrap, wrap_fields
from app.config import settings
from app.logging_config import get_logger
from app.models.cluster import ClusterItem, ContentCluster
from app.models.embedding import Embedding
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent

log = get_logger(__name__)

# Cosine band where we ask the LLM. Below this we assume genuinely different;
# above cluster_threshold the semantic dedup already merged them.
# 0.45 floor catches cross-language same-event pairs (ES<->EN land ~0.45-0.60)
# and opinion-angle coverage; the LLM same-event judge is the safety gate.
BORDERLINE_MIN = 0.45
# Process at most this many merge candidates per run (cost control).
MAX_PAIRS_PER_RUN = 150
# Recompute pairs and re-merge until stable (merges change representatives,
# exposing new borderline pairs). Bounded to avoid runaway cost.
MAX_ROUNDS = 8

# Tags too generic to count as a shared "entity" signal on their own.
TAG_STOPLIST = {
    "ai", "artificial intelligence", "ia", "ml", "machine learning", "llm", "llms",
    "technology", "tech", "software", "genai", "generative ai", "deep learning",
    "model", "models", "startup", "funding",
}
# Max entity-overlap pairs to LLM-judge per round (cost control).
MAX_ENTITY_PAIRS = 60


@dataclass
class MergeStats:
    pairs_evaluated: int = 0
    pairs_merged: int = 0


class ClusterMergerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def merge_borderline(self) -> MergeStats:
        """Run merge rounds until no further merges happen (or MAX_ROUNDS).
        Each round recomputes the borderline pairs, since merging changes
        cluster representatives and surfaces new same-event candidates."""
        total = MergeStats()
        for rnd in range(MAX_ROUNDS):
            round_stats = await self._merge_one_round()
            total.pairs_evaluated += round_stats.pairs_evaluated
            total.pairs_merged += round_stats.pairs_merged
            if round_stats.pairs_merged == 0:
                break
        log.info("merge.done", **total.__dict__)
        return total

    async def _merge_one_round(self) -> MergeStats:
        stats = MergeStats()
        # Candidate source 1: cosine borderline band.
        cosine_pairs = await self._find_borderline_pairs(limit=MAX_PAIRS_PER_RUN)
        # Candidate source 2: clusters sharing ≥2 tags incl. ≥1 specific entity,
        # even when cosine is too low to be a borderline pair (catches cross-
        # language coverage and same-subject/different-angle stories).
        entity_pairs = await self._find_entity_overlap_pairs(limit=MAX_ENTITY_PAIRS)
        # Union, dedup by unordered cluster-id pair (cosine pairs take priority
        # for the displayed cosine value).
        seen_keys: set[frozenset[int]] = set()
        pairs: list[tuple] = []
        for p in cosine_pairs + entity_pairs:
            key = frozenset((p[0], p[1]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pairs.append(p)
        if not pairs:
            log.info("merge.no_pairs")
            return stats

        log.info("merge.candidates", count=len(pairs), cosine=len(cosine_pairs), entity=len(entity_pairs))
        # Union-find redirect map: a merged-away cluster points at its survivor.
        # The pair list is computed once up front, so as we delete clusters we
        # must resolve every pair's endpoints to their current surviving root
        # before touching the DB — otherwise we'd re-point items into a cluster
        # that an earlier merge already deleted (FK violation).
        redirect: dict[int, int] = {}

        def root(cid: int) -> int:
            seen: list[int] = []
            while cid in redirect:
                seen.append(cid)
                cid = redirect[cid]
            for s in seen:
                redirect[s] = cid  # path compression
            return cid

        for (cluster_a, cluster_b, cosine, item_a, item_b) in pairs:
            ra, rb = root(cluster_a), root(cluster_b)
            if ra == rb:
                continue  # already in the same cluster via a prior merge
            stats.pairs_evaluated += 1
            try:
                same = await self._llm_same_event(item_a, item_b)
            except Exception as e:
                log.warning("merge.llm_failed", err=str(e))
                continue
            if not same:
                continue
            await self._merge(ra, rb)
            redirect[rb] = ra  # rb no longer exists; resolve future refs to ra
            stats.pairs_merged += 1
            log.info("merge.merged", from_cluster=rb, into=ra, cosine=round(cosine, 3))
        await self.session.commit()
        return stats

    async def _find_borderline_pairs(self, limit: int) -> list[tuple]:
        """Find cluster pairs whose representative embeddings sit in the
        [BORDERLINE_MIN, cluster_threshold) cosine band.
        Returns (cluster_a, cluster_b, cosine, raw_a, raw_b)."""
        since = datetime.now(timezone.utc) - timedelta(days=settings.dedup_lookback_days)
        sql = text(
            """
            SELECT a_cluster.id AS cluster_a,
                   b_cluster.id AS cluster_b,
                   (1 - (a_emb.embedding <=> b_emb.embedding))::float AS cosine,
                   a_raw.id AS raw_a,
                   b_raw.id AS raw_b
            FROM content_clusters AS a_cluster
              JOIN raw_content   AS a_raw     ON a_raw.id = a_cluster.representative_content_id
              JOIN embeddings    AS a_emb     ON a_emb.raw_content_id = a_raw.id
              JOIN content_clusters AS b_cluster ON b_cluster.id > a_cluster.id
              JOIN raw_content   AS b_raw     ON b_raw.id = b_cluster.representative_content_id
              JOIN embeddings    AS b_emb     ON b_emb.raw_content_id = b_raw.id
            WHERE a_raw.fetched_at >= :since
              AND b_raw.fetched_at >= :since
              AND (1 - (a_emb.embedding <=> b_emb.embedding)) >= :lo
              AND (1 - (a_emb.embedding <=> b_emb.embedding)) <  :hi
            ORDER BY cosine DESC
            LIMIT :lim
            """
        )
        res = await self.session.execute(
            sql,
            {
                "since": since,
                "lo": BORDERLINE_MIN,
                "hi": settings.cluster_threshold,
                "lim": limit,
            },
        )
        return [
            (int(r.cluster_a), int(r.cluster_b), float(r.cosine), int(r.raw_a), int(r.raw_b))
            for r in res.all()
        ]

    async def _find_entity_overlap_pairs(self, limit: int) -> list[tuple]:
        """Pairs of cluster representatives that share >=2 key_topics including
        >=1 specific (non-generic) entity. Cosine-agnostic: this is the lever for
        same-subject stories that sit below the cosine floor. Ranked by overlap
        strength. Returns (cluster_a, cluster_b, score, raw_a, raw_b)."""
        since = datetime.now(timezone.utc) - timedelta(days=settings.dedup_lookback_days)
        rows = await self.session.execute(
            select(
                ContentCluster.id,
                ContentCluster.representative_content_id,
                ProcessedContent.key_topics,
            )
            .join(RawContent, RawContent.id == ContentCluster.representative_content_id)
            .join(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
            .where(RawContent.fetched_at >= since)
            .where(ProcessedContent.is_noise.is_(False))
        )
        reps: list[tuple[int, int, set[str]]] = []
        for cid, rep_id, topics in rows.all():
            tags = {str(t).strip().lower() for t in (topics or []) if str(t).strip()}
            if tags:
                reps.append((int(cid), int(rep_id), tags))

        # A qualifying pair needs >=1 SPECIFIC (non-stoplist) shared tag, so index reps
        # by their specific tags and only compare pairs that co-occur in at least one —
        # provably the same candidate set as the all-pairs scan, but near-linear instead
        # of O(n^2) and immune to a ubiquitous generic tag blowing it up.
        by_tag: dict[str, list[int]] = {}
        for idx, (_cid, _raw, tags) in enumerate(reps):
            for t in (tags - TAG_STOPLIST):
                by_tag.setdefault(t, []).append(idx)
        candidate_pairs: set[tuple[int, int]] = set()
        for idxs in by_tag.values():
            for a_i in range(len(idxs)):
                for b_i in range(a_i + 1, len(idxs)):
                    i, j = idxs[a_i], idxs[b_i]
                    candidate_pairs.add((i, j) if i < j else (j, i))

        scored: list[tuple] = []
        for i, j in candidate_pairs:
            cid_a, raw_a, tags_a = reps[i]
            cid_b, raw_b, tags_b = reps[j]
            shared = tags_a & tags_b
            if len(shared) < 2:
                continue
            specific = shared - TAG_STOPLIST
            if not specific:
                continue
            # score: specific entities weigh more than generic shared tags.
            score = len(specific) * 2 + len(shared)
            a, b = (cid_a, raw_a), (cid_b, raw_b)
            if cid_a > cid_b:  # normalize a<b to match redirect expectations
                a, b = (cid_b, raw_b), (cid_a, raw_a)
            scored.append((a[0], b[0], float(score), a[1], b[1]))
        scored.sort(key=lambda t: t[2], reverse=True)
        return scored[:limit]

    async def merge_by_llm_grouping(self, min_confidence: str = "high") -> MergeStats:
        """Holistic judge: show the LLM every recent cluster (id + headline +
        one-liner) at once and ask it to group same-story clusters. Catches
        same-subject/different-angle and cross-language dups that pairwise cosine
        and entity overlap miss, because the model reasons over the full set.
        One LLM call for the whole corpus."""
        stats = MergeStats()
        since = datetime.now(timezone.utc) - timedelta(days=settings.dedup_lookback_days)
        rows = await self.session.execute(
            select(
                ContentCluster.id,
                RawContent.title,
                ProcessedContent.cleaned_summary,
            )
            .join(RawContent, RawContent.id == ContentCluster.representative_content_id)
            .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
            .where(RawContent.fetched_at >= since)
            .where((ProcessedContent.is_noise.is_(False)) | (ProcessedContent.id.is_(None)))
        )
        clusters = rows.all()
        if len(clusters) < 2:
            return stats

        valid_ids = {int(c[0]) for c in clusters}
        lines = []
        for cid, title, summary in clusters:
            t = neutralize((title or "").strip(), 120).replace("\n", " ")
            one_liner = neutralize((summary or "").strip(), 160).replace("\n", " ")
            lines.append(f"[{int(cid)}] {t}" + (f" — {one_liner}" if one_liner else ""))
        listing = "\n".join(lines)

        try:
            result = await json_completion(
                system=INJECTION_GUARD + CLUSTER_GROUPING_V1_SYSTEM,
                user=CLUSTER_GROUPING_V1_USER.format(clusters=wrap(listing, 12000)),
                temperature=0.0,
            )
        except Exception as e:
            log.warning("merge.grouping_llm_failed", err=str(e))
            return stats

        accept = {"high", "medium"} if min_confidence == "medium" else {"high"}
        redirect: dict[int, int] = {}

        def root(cid: int) -> int:
            while cid in redirect:
                cid = redirect[cid]
            return cid

        for group in result.get("groups", []) or []:
            conf = (group.get("confidence") or "low").lower()
            if conf not in accept:
                continue
            ids = [int(x) for x in (group.get("cluster_ids") or []) if int(x) in valid_ids]
            ids = sorted(set(ids))
            if len(ids) < 2:
                continue
            stats.pairs_evaluated += 1
            # Merge all into the lowest surviving id.
            target = root(ids[0])
            for other in ids[1:]:
                ro = root(other)
                if ro == target:
                    continue
                await self._merge(target, ro)
                redirect[ro] = target
                stats.pairs_merged += 1
                log.info("merge.grouped", into=target, dropped=ro, story=group.get("story", "")[:60])
        await self.session.commit()
        log.info("merge.grouping_done", **stats.__dict__)
        return stats

    async def _llm_same_event(self, raw_a_id: int, raw_b_id: int) -> bool:
        # Fetch title + cleaned_summary (or title only) for each side.
        async def _payload(rid: int) -> tuple[str, str]:
            row = await self.session.execute(
                select(RawContent.title, ProcessedContent.cleaned_summary)
                .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
                .where(RawContent.id == rid)
            )
            r = row.first()
            if r is None:
                return ("", "")
            return (r[0] or "", r[1] or "")

        ta, sa = await _payload(raw_a_id)
        tb, sb = await _payload(raw_b_id)
        # Skip blanks: two empty payloads could be judged "same" spuriously.
        if not ta.strip() or not tb.strip():
            return False
        result = await json_completion(
            system=INJECTION_GUARD + SAME_EVENT_V1_SYSTEM,
            user=SAME_EVENT_V1_USER.format(
                items=wrap_fields(
                    max_len=600,
                    ITEM_A_TITLE=ta,
                    ITEM_A_SUMMARY=sa or "(no summary)",
                    ITEM_B_TITLE=tb,
                    ITEM_B_SUMMARY=sb or "(no summary)",
                ),
            ),
            temperature=0.0,
        )
        same = bool(result.get("same_event", False))
        conf = (result.get("confidence") or "low").lower()
        # Only merge on high/medium confidence to avoid bad merges.
        return same and conf in ("high", "medium")

    async def _merge(self, into_id: int, from_id: int) -> None:
        """Move all cluster_items from `from_id` into `into_id`, then drop the
        `from_id` cluster. Avoid duplicate (cluster_id, raw_content_id) keys."""
        # Items currently in 'into' — we already have them, don't duplicate.
        existing_q = await self.session.execute(
            select(ClusterItem.raw_content_id).where(ClusterItem.cluster_id == into_id)
        )
        existing = {int(r[0]) for r in existing_q.all()}

        # Items in 'from': re-point the ones 'into' lacks; explicitly delete the
        # ones 'into' already has so the UPDATE can never hit the composite PK
        # (cluster_id, raw_content_id). Leftover 'from' items would otherwise
        # cascade-delete on the cluster drop anyway — we just do it eagerly to
        # keep the UPDATE conflict-free.
        items_q = await self.session.execute(
            select(ClusterItem.raw_content_id).where(ClusterItem.cluster_id == from_id)
        )
        for (raw_id,) in items_q.all():
            if int(raw_id) in existing:
                await self.session.execute(
                    delete(ClusterItem).where(
                        ClusterItem.cluster_id == from_id,
                        ClusterItem.raw_content_id == raw_id,
                    )
                )
                continue
            await self.session.execute(
                update(ClusterItem)
                .where(
                    ClusterItem.cluster_id == from_id,
                    ClusterItem.raw_content_id == raw_id,
                )
                .values(cluster_id=into_id)
            )
            existing.add(int(raw_id))

        # Keep the survivor's representative valid: if it points at a row that is
        # no longer a member (or is NULL), repoint it to a current member.
        await self._ensure_representative(into_id)

        # Drop the 'from' cluster (any leftover cluster_items cascade-delete).
        await self.session.execute(delete(ContentCluster).where(ContentCluster.id == from_id))

    async def _ensure_representative(self, cluster_id: int) -> None:
        """Guarantee the cluster's representative is a current, non-pruned member.
        A pruned member has no embedding/text, so it must never be the rep.
        Covers merges and retention deletes that can leave it NULL/dangling."""
        cluster = await self.session.get(ContentCluster, cluster_id)
        if cluster is None:
            return
        rows = (
            await self.session.execute(
                select(ClusterItem.raw_content_id, RawContent.embedding_pruned)
                .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
                .where(ClusterItem.cluster_id == cluster_id)
            )
        ).all()
        if not rows:
            return
        pruned_ids = {int(r[0]) for r in rows if r[1]}
        all_ids = sorted(int(r[0]) for r in rows)
        non_pruned = sorted(i for i in all_ids if i not in pruned_ids)
        rep = cluster.representative_content_id
        rep_ok = rep in all_ids and rep not in pruned_ids
        if not rep_ok:
            cluster.representative_content_id = non_pruned[0] if non_pruned else all_ids[0]


# --------------------------------------------------------------------- #
# One-time helper: prune orphan clusters (no representative or empty).
# --------------------------------------------------------------------- #
async def prune_orphan_clusters(session: AsyncSession) -> int:
    empty_q = (
        select(ContentCluster.id)
        .outerjoin(ClusterItem, ClusterItem.cluster_id == ContentCluster.id)
        .group_by(ContentCluster.id)
        .having(func.count(ClusterItem.raw_content_id) == 0)
    )
    empty = [int(r[0]) for r in (await session.execute(empty_q)).all()]
    if empty:
        await session.execute(delete(ContentCluster).where(ContentCluster.id.in_(empty)))
        await session.commit()
    return len(empty)


async def repair_orphan_representatives(session: AsyncSession) -> int:
    """Repoint clusters whose representative_content_id is NULL or no longer a
    member (e.g. after retention deleted the representative raw row, which the
    FK sets to NULL). Without this such clusters vanish from read endpoints that
    inner-join on the representative."""
    cluster_rows = await session.execute(
        select(ContentCluster.id, ContentCluster.representative_content_id)
    )
    fixed = 0
    for cid, rep in cluster_rows.all():
        rows = (
            await session.execute(
                select(ClusterItem.raw_content_id, RawContent.embedding_pruned)
                .join(RawContent, RawContent.id == ClusterItem.raw_content_id)
                .where(ClusterItem.cluster_id == cid)
            )
        ).all()
        if not rows:
            continue  # empty clusters handled by prune_orphan_clusters
        pruned_ids = {int(r[0]) for r in rows if r[1]}
        all_ids = sorted(int(r[0]) for r in rows)
        non_pruned = sorted(i for i in all_ids if i not in pruned_ids)
        rep_ok = rep is not None and int(rep) in all_ids and int(rep) not in pruned_ids
        if not rep_ok:
            cluster = await session.get(ContentCluster, int(cid))
            if cluster is not None:
                cluster.representative_content_id = non_pruned[0] if non_pruned else all_ids[0]
                fixed += 1
    if fixed:
        await session.commit()
    return fixed


async def prune_duplicate_members(session: AsyncSession) -> int:
    """Storage saver: for non-representative cluster members, delete the heavy
    embedding and blank raw_text, marking the row embedding_pruned. The row stays
    so cross-source counts (distinct_sources) keep working; embed_pending skips it
    so it's never re-embedded; future dedup compares against representatives."""
    member_ids_subq = (
        select(ClusterItem.raw_content_id)
        .join(ContentCluster, ContentCluster.id == ClusterItem.cluster_id)
        .where(ClusterItem.raw_content_id != ContentCluster.representative_content_id)
    )
    target = (
        await session.execute(
            select(RawContent.id)
            .where(RawContent.id.in_(member_ids_subq))
            .where(RawContent.embedding_pruned.is_(False))
        )
    ).scalars().all()
    if not target:
        return 0
    ids = [int(i) for i in target]
    await session.execute(delete(Embedding).where(Embedding.raw_content_id.in_(ids)))
    await session.execute(
        update(RawContent)
        .where(RawContent.id.in_(ids))
        .values(raw_text="", embedding_pruned=True)
    )
    await session.commit()
    log.info("prune.duplicate_members", pruned=len(ids))
    return len(ids)
