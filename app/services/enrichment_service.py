from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_client import json_completion
from app.ai.prompts import (
    CLUSTER_TOPIC_V1_SYSTEM,
    CLUSTER_TOPIC_V1_USER,
    ENRICH_V1_SYSTEM,
    ENRICH_V1_USER,
    INJECTION_GUARD,
    LINKEDIN_V1_SYSTEM,
    LINKEDIN_V1_USER,
)
from app.ai.sanitize import (
    OUT_TITLE_MAX,
    clean_model_text,
    neutralize,
    wrap,
    wrap_article,
    wrap_fields,
)
from app.logging_config import get_logger
from app.models.cluster import ClusterItem, ContentCluster
from app.models.processed_content import ProcessedContent
from app.models.raw_content import RawContent
from app.repositories.cluster_repo import ClusterRepository
from app.repositories.processed_repo import ProcessedContentRepository

log = get_logger(__name__)

_MAX_BODY = 8000


class EnrichmentService:
    """Runs enrichment + LinkedIn angle generation once per cluster representative.

    Cluster members inherit at the API layer; we do not write per-member duplicates.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cluster_repo = ClusterRepository(session)
        self.proc_repo = ProcessedContentRepository(session)

    async def enrich_pending(self) -> int:
        clusters_to_process = await self._clusters_needing_enrichment()
        log.info("enrich.candidates", count=len(clusters_to_process))
        done = 0
        for cluster_id, rep_id in clusters_to_process:
            try:
                await self._enrich_cluster(cluster_id, rep_id)
                done += 1
            except Exception as e:
                log.error("enrich.failed", cluster_id=cluster_id, err=str(e))
        log.info("enrich.done", clusters_enriched=done)
        return done

    async def _clusters_needing_enrichment(self) -> list[tuple[int, int]]:
        stmt = (
            select(ContentCluster.id, ContentCluster.representative_content_id)
            .join(RawContent, RawContent.id == ContentCluster.representative_content_id)
            .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == ContentCluster.representative_content_id)
            .where(
                (
                    (ProcessedContent.cleaned_summary.is_(None))
                    # re-enrich English-era rows that lack the Spanish title → re-translate
                    | (ProcessedContent.title_es.is_(None))
                )
                & (ProcessedContent.is_noise.is_(False))
            )
        )
        res = await self.session.execute(stmt)
        out: list[tuple[int, int]] = []
        for cid, rid in res.all():
            if rid is not None:
                out.append((int(cid), int(rid)))
        return out

    async def _enrich_cluster(self, cluster_id: int, representative_id: int) -> None:
        # Reselect representative based on member importance scores if any exist.
        representative_id = await self._reselect_representative(cluster_id, representative_id)
        raw = await self.session.get(RawContent, representative_id)
        if raw is None:
            return

        enrichment = await json_completion(
            system=INJECTION_GUARD + ENRICH_V1_SYSTEM,
            user=ENRICH_V1_USER.format(
                article=wrap_article(
                    title=raw.title, url=raw.url, body=raw.raw_text, max_body=_MAX_BODY
                ),
            ),
            temperature=0.2,
        )

        scores = enrichment.get("scores", {})
        insights = enrichment.get("insights", {})
        # Free-text model output is published on the public site — scrub markup and
        # control chars here, at the point it enters the DB, so no renderer downstream
        # has to be trusted to do it. Enums/scores are validated separately below.
        summary = clean_model_text(enrichment.get("cleaned_summary"))
        topics = enrichment.get("key_topics", [])
        content_type = enrichment.get("content_type")
        if content_type:
            insights = {**insights, "content_type": content_type}

        linkedin = await json_completion(
            system=INJECTION_GUARD + LINKEDIN_V1_SYSTEM,
            user=LINKEDIN_V1_USER.format(
                article=wrap_fields(
                    TITLE=raw.title,
                    SUMMARY=summary or "",
                    INSIGHTS=json.dumps(insights, ensure_ascii=False),
                    max_len=4000,
                ),
            ),
            temperature=0.7,
        )

        await self.proc_repo.upsert_for(
            raw_content_id=representative_id,
            cleaned_summary=summary,
            title_es=clean_model_text(enrichment.get("title_es"), OUT_TITLE_MAX),
            key_topics=topics,
            novelty_score=_safe_int(scores.get("novelty")),
            importance_score=_safe_int(scores.get("importance")),
            linkedin_potential_score=_safe_int(scores.get("linkedin_potential")),
            business_impact_score=_safe_int(scores.get("business_impact")),
            ai_generated_insights=insights,
            linkedin_angles=linkedin,
            is_noise=False,
        )

        await self._name_cluster_if_unset(cluster_id)
        await self.session.commit()

    async def _name_cluster_if_unset(self, cluster_id: int) -> None:
        cluster = await self.session.get(ContentCluster, cluster_id)
        if cluster is None or cluster.cluster_topic:
            return
        member_titles = await self._cluster_titles(cluster_id, limit=8)
        if not member_titles:
            return
        try:
            payload = await json_completion(
                system=INJECTION_GUARD + CLUSTER_TOPIC_V1_SYSTEM,
                user=CLUSTER_TOPIC_V1_USER.format(
                    titles=wrap("\n".join(f"- {neutralize(t, 300)}" for t in member_titles), 4000)
                ),
                temperature=0.2,
            )
            topic = clean_model_text(payload.get("topic"), OUT_TITLE_MAX) or ""
            if topic:
                await self.cluster_repo.set_topic(cluster_id, topic)
        except Exception as e:
            log.warning("enrich.topic_failed", cluster_id=cluster_id, err=str(e))

    async def _reselect_representative(self, cluster_id: int, current_id: int) -> int:
        """Pick the member with the highest importance_score. Ties broken by earliest published.
        Falls back to current_id when no member has been scored yet."""
        stmt = (
            select(RawContent.id, ProcessedContent.importance_score, RawContent.published_at)
            .join(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
            .outerjoin(ProcessedContent, ProcessedContent.raw_content_id == RawContent.id)
            .where(ClusterItem.cluster_id == cluster_id)
            # Never promote a pruned member (raw_text blanked) to representative —
            # enrichment would then run on an empty body. Mirrors cluster_merger.
            .where(RawContent.embedding_pruned.is_(False))
        )
        res = await self.session.execute(stmt)
        rows = res.all()
        if not rows:
            return current_id
        best = max(
            rows,
            key=lambda r: (
                int(r[1]) if r[1] is not None else -1,
                # earlier published_at wins ties — invert so max() picks it
                -(r[2].timestamp() if r[2] is not None else 0),
            ),
        )
        new_rep = int(best[0])
        if new_rep != current_id:
            cluster = await self.session.get(ContentCluster, cluster_id)
            if cluster is not None:
                cluster.representative_content_id = new_rep
                await self.session.flush()
        return new_rep

    async def _cluster_titles(self, cluster_id: int, *, limit: int) -> list[str]:
        stmt = (
            select(RawContent.title)
            .join(ClusterItem, ClusterItem.raw_content_id == RawContent.id)
            .where(ClusterItem.cluster_id == cluster_id)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return [str(r[0]) for r in res.all() if r[0]]


def _safe_int(v: object) -> int | None:
    try:
        if v is None:
            return None
        n = int(v)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))
