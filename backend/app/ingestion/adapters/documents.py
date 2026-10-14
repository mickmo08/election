"""Licensed news / permitted public-discussion items (JSON Lines) for aggregate issue analysis."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select

from ...models import Document
from ...services.issues import content_hash, detect_languages, jaccard_estimate, minhash
from ..framework import FetchedFile, Issue, RunContext, SourceAdapter, StructuralError, register
from ..loaders import Resolver
from ..validation import parse_datetime

NEAR_DUP = 0.8
# Fields that would identify individuals are rejected outright (aggregate analysis only).
FORBIDDEN_FIELDS = {"author", "author_id", "username", "user_id", "handle", "email", "profile_url", "followers"}


class DocumentsAdapter(SourceAdapter):
    key = "documents_jsonl"
    version = "1.0.0"
    schema_version = "documents-v1"

    def process(self, ctx: RunContext, files: list[FetchedFile]) -> None:
        if not ctx.source.permits_text_analysis:
            raise StructuralError(
                [
                    Issue(
                        "source",
                        "licence",
                        f"{ctx.source.key} licence does not permit text " "analysis",
                        blocking=True,
                        suggested_action="Record a licence that permits text and data mining.",
                    )
                ]
            )
        tenant_id = ctx.params.get("tenant_id")
        for f in files:
            raw = ctx.raw_file_for(f)
            for i, line in enumerate(f.content.decode("utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                ref = f"{f.filename} line {i}"
                try:
                    item = json.loads(line)
                except ValueError:
                    ctx.quarantine(Issue(ref, "json", "invalid JSON line"))
                    continue
                if FORBIDDEN_FIELDS & item.keys():
                    ctx.quarantine(
                        Issue(
                            ref,
                            "personal_data",
                            "item contains author/user fields; rejected",
                            payload={"fields": sorted(FORBIDDEN_FIELDS & item.keys())},
                            suggested_action="Strip author identifiers upstream.",
                        )
                    )
                    continue
                missing = [
                    k for k in ("external_id", "kind", "title", "body", "published_at", "country") if not item.get(k)
                ]
                if missing:
                    ctx.quarantine(Issue(ref, "schema", f"missing fields {missing}"))
                    continue
                if item["kind"] not in ("news", "public_discussion"):
                    ctx.quarantine(Issue(ref, "kind", "kind must be news or public_discussion"))
                    continue
                issues: list[Issue] = []
                published = parse_datetime(item["published_at"], "published_at", ref, issues)
                if published is None:
                    ctx.issues.extend(issues)
                    continue
                exists = ctx.db.scalar(
                    select(Document.id).where(
                        Document.source_id == ctx.source.id, Document.external_id == str(item["external_id"])
                    )
                )
                if exists:
                    ctx.count("already_present")
                    continue
                text = f"{item['title']}. {item['body']}"
                lang, props = detect_languages(text)
                chash = content_hash(item["body"])  # dedupe on body: syndication often rewrites headlines
                sig = minhash(item["body"])
                dup_of = ctx.db.scalar(
                    select(Document.id)
                    .where(Document.content_hash == chash, Document.duplicate_of_id.is_(None))
                    .limit(1)
                )
                if dup_of is None:
                    window = ctx.db.execute(
                        select(Document.id, Document.minhash).where(
                            Document.duplicate_of_id.is_(None),
                            Document.country_code == item["country"],
                            Document.published_at.between(published - timedelta(days=3), published + timedelta(days=3)),
                        )
                    ).all()
                    for did, other in window:
                        if jaccard_estimate(sig, other) >= NEAR_DUP:
                            dup_of = did
                            break
                unit, geo_conf = None, "none"
                if item.get("admin_unit"):
                    unit = Resolver(ctx, item["country"]).unit(item["admin_unit"])
                    geo_conf = "high" if unit else "none"
                ctx.db.add(
                    Document(
                        tenant_id=tenant_id,
                        source_id=ctx.source.id,
                        external_id=str(item["external_id"]),
                        kind=item["kind"],
                        url=item.get("url"),
                        title=item["title"],
                        body=item["body"],
                        published_at=published,
                        language=item.get("language") or lang,
                        languages_detected=props,
                        country_code=item["country"],
                        admin_unit_id=unit.id if unit else None,
                        geo_confidence=geo_conf,
                        content_hash=chash,
                        minhash=sig,
                        duplicate_of_id=dup_of,
                        raw_file_id=raw.id,
                    )
                )
                ctx.db.flush()
                ctx.count("duplicates" if dup_of else "documents")


register(DocumentsAdapter())
