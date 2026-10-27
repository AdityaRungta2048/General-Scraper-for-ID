"""IdentityResolver: resolves ONE unique source id into a cacheable, auditable resolution.

    verify source exists → generate candidates → verify identity → aggregate
    (or, if the source does not exist, a strictly deterministic same-name check on
    the target platform, verified only by an explicit back-link)

A current name the user typed in the sheet's "renamed_to" column (looked up by hand on
streamscharts.com) replaces the source ID when that account exists. With a Streams Charts key,
renamed channels are also followed automatically: a source ID that no longer
exists is looked up under its earlier name, and when nothing on the other platform has the
source's name, so is the other platform's channel that used to have it.

Manual review verdicts are applied afterwards (``apply_manual_reviews``) so cached
resolutions never bake in human decisions.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.cache.service import CacheService
from app.logging_setup import get_logger
from app.matching.candidates import CandidateGenerator
from app.matching.decision import CandidateEvaluation, Decision, aggregate
from app.matching.names import UsernameMatcher
from app.matching.normalize import fold_accents, normalize_username
from app.matching.signals import Family, Signal, Strength
from app.matching.social import canonical_platform_handle, extract_identities
from app.matching.text import COUNTRY_LANGUAGES, GENERIC_CATEGORIES, normalize_language
from app.matching.verifier import IdentityVerifier
from app.platforms.base import PlatformAdapter, Profile, dedupe, written_id
from app.platforms.streams_charts import StreamsChartsRenames
from app.services.stores import ProfileStore
from app.version import MATCHING_ENGINE_VERSION

log = get_logger("resolver")


def display_id(profile: Profile) -> str:
    return written_id(profile.platform, profile.username, profile.display_name)


class IdentityResolver:
    def __init__(
        self,
        adapters: dict[str, PlatformAdapter],
        generator: CandidateGenerator,
        verifier: IdentityVerifier,
        cache: CacheService,
        profile_store: ProfileStore | None = None,
        resolution_ttl: int = 3 * 86400,
        renames: StreamsChartsRenames | None = None,
    ) -> None:
        self.adapters = adapters
        self.generator = generator
        self.verifier = verifier
        self.cache = cache
        self.profile_store = profile_store
        self.resolution_ttl = resolution_ttl
        self.renames = renames

    def cache_key(
        self,
        source_platform: str,
        target_platform: str,
        key: str,
        country: str | None,
        renamed_to: str | None = None,
    ) -> str:
        return (
            f"{MATCHING_ENGINE_VERSION}|{source_platform}>{target_platform}|{key}|"
            f"{(country or '').strip().lower()}|{(renamed_to or '').strip().lower()}"
        )

    async def resolve(
        self,
        source_platform: str,
        target_platform: str,
        raw_value: str,
        country: str | None,
        rejected: set[str] | None = None,
        renamed_to: str | None = None,
    ) -> dict[str, Any]:
        src_adapter = self.adapters[source_platform]
        tgt_platform = target_platform
        tgt_adapter = self.adapters[tgt_platform]
        key = src_adapter.normalize_handle(raw_value)
        cache_key = self.cache_key(
            source_platform, tgt_platform, key or f"invalid:{raw_value.strip().lower()}", country, renamed_to
        )
        if not rejected:
            cached = self.cache.get("resolution", cache_key)
            if cached is not None:
                return {**cached, "from_cache": True}

        base: dict[str, Any] = {
            "engine_version": MATCHING_ENGINE_VERSION,
            "source_platform": source_platform,
            "target_platform": tgt_platform,
            "source_value": raw_value,
            "source_key": key,
            "country": country,
            "resolved_at": datetime.now(UTC).isoformat(),
        }

        source: Profile | None = None
        new_key = src_adapter.normalize_handle(renamed_to) if renamed_to else None
        if new_key is not None and new_key != key:
            found = await src_adapter.find_exact_accounts(src_adapter.existence_variants(new_key))
            current = next((p for p in found.values() if p is not None), None)
            if current is not None:
                source = replace(current, former_names=[key] if key else [], rename_confirmed=True)
                base["renamed_source"] = {"from": key or raw_value, "to": current.username, "by": "sheet"}
            else:
                base["renamed_to_not_found"] = renamed_to
        if source is None and key is not None:
            found = await src_adapter.find_exact_accounts(src_adapter.existence_variants(key))
            source = next((p for p in found.values() if p is not None), None)
            if source is None and self.renames is not None:
                renamed = await self.renames.renamed_account(src_adapter, key)
                # an unconfirmed rename is not enough to treat the account as the sheet's
                if renamed is not None and renamed.rename_confirmed:
                    source = renamed
                    base["renamed_source"] = {"from": key, "to": renamed.username}

        if source is None:
            result = await self._resolve_source_missing(
                base, raw_value, key, src_adapter, tgt_adapter, rejected
            )
        else:
            result = await self._resolve_source_exists(
                base, source, country, src_adapter, tgt_adapter, rejected
            )
        result = apply_match_rules(result)
        if not rejected:
            self.cache.set(
                "resolution",
                cache_key,
                result,
                self.resolution_ttl,
                source="engine",
                source_version=MATCHING_ENGINE_VERSION,
            )
        return result

    async def _resolve_source_exists(
        self,
        base: dict[str, Any],
        source: Profile,
        country: str | None,
        src_adapter: PlatformAdapter,
        tgt_adapter: PlatformAdapter,
        rejected: set[str] | None,
    ) -> dict[str, Any]:
        s_ids = extract_identities(source)
        if self.profile_store:
            self.profile_store.upsert(source, s_ids)
        refs = await self.generator.generate(source, tgt_adapter, s_ids, rejected)
        pairs = [(r.profile, sorted(r.via)) for r in refs if r.profile is not None]
        pairs += await self._former_name_targets(source, tgt_adapter, pairs, rejected)
        if self.profile_store:
            for prof, _ in pairs:
                self.profile_store.upsert(prof, extract_identities(prof))
        evals = await self.verifier.verify(source, pairs, country, src_adapter, tgt_adapter)
        if self.renames is not None and not any(rule_hits(source.to_dict(), e.to_dict()) for e in evals):
            renamed = await self._renamed_targets(source, tgt_adapter, pairs, rejected)
            if renamed:
                evals += await self.verifier.verify(source, renamed, country, src_adapter, tgt_adapter)
        agg = aggregate(evals)
        best = agg.best
        ranked = sorted(evals, key=lambda e: (-e.confidence, -e.points))[:10]
        if best is not None and best not in ranked:
            ranked = [best, *ranked[:9]]
        return {
            **base,
            "source_status": "EXISTS",
            "source_profile": source.to_dict(),
            "source_socials": [i.to_dict() for i in s_ids],
            "decision": agg.decision.value,
            "target_status": None,
            "matched_username": best.candidate.username if best and agg.decision == Decision.MATCH else None,
            "matched_id": display_id(best.candidate) if best and agg.decision == Decision.MATCH else None,
            "review_candidate": best.candidate.username if best and agg.decision == Decision.REVIEW else None,
            "confidence": best.confidence if best else None,
            "reason": agg.reason,
            "candidate_count": len(evals),
            "candidates": [e.to_dict() for e in ranked],
        }

    async def _former_name_targets(
        self,
        source: Profile,
        tgt_adapter: PlatformAdapter,
        pairs: list[tuple[Profile, list[str]]],
        rejected: set[str] | None,
    ) -> list[tuple[Profile, list[str]]]:
        """Target accounts that have a renamed source's earlier name (official lookup, free)."""
        known = {p.username for p, _ in pairs} | set(rejected or ())
        handles = [h for h in (tgt_adapter.to_handle(n) for n in source.former_names) if h and h not in known]
        if not handles:
            return []
        found = await tgt_adapter.find_exact_accounts(dedupe(handles))
        return [(p, ["source_former_name"]) for p in found.values() if p is not None]

    async def _renamed_targets(
        self,
        source: Profile,
        tgt_adapter: PlatformAdapter,
        pairs: list[tuple[Profile, list[str]]],
        rejected: set[str] | None,
    ) -> list[tuple[Profile, list[str]]]:
        """Target accounts that were renamed away from one of the source's names (Streams
        Charts). Asked only when no candidate matched, for names nobody uses today."""
        assert self.renames is not None
        known = {p.username for p, _ in pairs} | set(rejected or ())
        names = [source.username, *source.former_names]
        out: list[tuple[Profile, list[str]]] = []
        for handle in dedupe([h for h in (tgt_adapter.to_handle(n) for n in names) if h]):
            if await tgt_adapter.find_exact_account(handle) is not None:
                continue  # the name is in use today, so it is not a renamed channel
            prof = await self.renames.renamed_account(tgt_adapter, handle)
            if prof is not None and prof.username not in known:
                known.add(prof.username)
                out.append((prof, ["streams_charts_rename"]))
        return out

    async def _resolve_source_missing(
        self,
        base: dict[str, Any],
        raw_value: str,
        key: str | None,
        src_adapter: PlatformAdapter,
        tgt_adapter: PlatformAdapter,
        rejected: set[str] | None,
    ) -> dict[str, Any]:
        """Source account does not exist. Only a deterministic same-name check is done on the
        target platform; a target account is VERIFIED only if it explicitly links back to the
        exact source id (or a human confirms it later)."""
        name = key or raw_value.strip().lstrip("@").lower()
        handles = dedupe(
            [h for h in (tgt_adapter.to_handle(name), tgt_adapter.to_handle(normalize_username(name))) if h]
        )
        found = await tgt_adapter.find_exact_accounts(handles) if handles else {}
        targets = [p for p in found.values() if p is not None and p.username not in (rejected or set())]
        if not targets and self.renames is not None:
            for handle in handles:
                prof = await self.renames.renamed_account(tgt_adapter, handle)
                if prof is not None and prof.username not in (rejected or set()):
                    targets.append(prof)
                    break
        src_canonical = canonical_platform_handle(src_adapter.platform, name)
        evals: list[CandidateEvaluation] = []
        verified: CandidateEvaluation | None = None
        for prof in targets:
            ids = extract_identities(prof)
            links_back = any(i.kind == src_adapter.platform and i.identity == src_canonical for i in ids)
            name_sig = UsernameMatcher(self.verifier.config).compare(
                Profile(platform=src_adapter.platform, username=name), prof
            )
            link_sig = Signal(
                "cross_link",
                Family.LINK,
                links_back,
                1.0 if links_back else None,
                self.verifier.config.cross_link_weight if links_back else 0.0,
                Strength.STRONG if links_back else Strength.NONE,
                f"{tgt_adapter.platform} profile links to {src_adapter.platform}/{name}"
                if links_back
                else f"{tgt_adapter.platform} profile does not link to {src_adapter.platform}/{name}",
                {"backward": links_back, "forward": False},
            )
            ev = CandidateEvaluation(prof, [link_sig, name_sig], discovered_via=["same_name_check"])
            ev.points = link_sig.points + name_sig.points
            if links_back:
                ev.decision, ev.confidence = Decision.MATCH, 95.0
                ev.reason = (
                    f"Source {src_adapter.platform} account does not exist; the {tgt_adapter.platform} "
                    f"account explicitly links to {src_adapter.platform}/{name}."
                )
                verified = verified or ev
            else:
                ev.decision, ev.confidence = Decision.REVIEW, 0.0
                ev.reason = (
                    f"Source {src_adapter.platform} account does not exist. A same-name "
                    f"{tgt_adapter.platform} account exists but nothing verifies it is the same creator."
                )
            evals.append(ev)
        if verified is not None:
            target_status, decision, best = "VERIFIED", Decision.MATCH, verified
        elif evals:
            target_status, decision, best = "EXISTS_UNVERIFIED", Decision.REVIEW, evals[0]
        else:
            target_status, decision, best = "NOT_FOUND", Decision.NO_MATCH, None
        if self.profile_store:
            for prof in targets:
                self.profile_store.upsert(prof, extract_identities(prof))
        reason = (
            best.reason
            if best
            else (
                f"Source {src_adapter.platform} account does not exist"
                + ("" if key else " (value is not a valid handle for that platform)")
                + f", and no same-name {tgt_adapter.platform} account exists."
            )
        )
        return {
            **base,
            "source_status": "NOT_FOUND",
            "source_profile": None,
            "source_socials": [],
            "decision": decision.value,
            "target_status": target_status,
            "matched_username": best.candidate.username if best and decision == Decision.MATCH else None,
            "matched_id": display_id(best.candidate) if best and decision == Decision.MATCH else None,
            "review_candidate": best.candidate.username if best and decision == Decision.REVIEW else None,
            # an unverified same-name account has no meaningful confidence score
            "confidence": best.confidence if best and target_status == "VERIFIED" else None,
            "reason": reason,
            "candidate_count": len(evals),
            "candidates": [e.to_dict() for e in evals],
        }


def apply_manual_reviews(resolution: dict[str, Any], verdicts: dict[str, str]) -> dict[str, Any]:
    """Apply stored human verdicts {target_username: CONFIRMED|REJECTED} to a resolution."""
    if not verdicts:
        return resolution
    res = dict(resolution)
    cands = [dict(c) for c in res.get("candidates", [])]
    for c in cands:
        verdict = verdicts.get(c["username"])
        if verdict:
            c["manual_verdict"] = verdict
    res["candidates"] = cands
    confirmed = [c for c in cands if c.get("manual_verdict") == "CONFIRMED"]
    if confirmed:
        c = confirmed[0]
        res.update(
            decision="MATCH",
            matched_username=c["username"],
            matched_id=_display_from_candidate(c),
            review_candidate=None,
            confidence=100.0,
            reason=(
                f"Confirmed by manual review ({c['platform']}/{c['username']}). "
                f"Engine said: {c.get('reason', '')}"
            ),
            manual=True,
        )
        if res.get("source_status") == "NOT_FOUND":
            res["target_status"] = "VERIFIED"
        return res
    rejected = {u for u, v in verdicts.items() if v == "REJECTED"}
    if not rejected:
        return res
    live = [c for c in cands if c["username"] not in rejected]
    matches = [c for c in live if c["decision"] == "MATCH"]
    reviews = sorted(
        (c for c in live if c["decision"] == "REVIEW"), key=lambda c: -(c.get("confidence") or 0)
    )
    if len(matches) == 1:
        c = matches[0]
        res.update(
            decision="MATCH",
            matched_username=c["username"],
            matched_id=_display_from_candidate(c),
            review_candidate=None,
            confidence=c["confidence"],
            reason=c["reason"],
        )
    elif len(matches) > 1 or reviews:
        c = matches[0] if matches else reviews[0]
        res.update(
            decision="REVIEW",
            matched_username=None,
            matched_id=None,
            review_candidate=c["username"],
            confidence=c["confidence"],
            reason=c["reason"],
        )
    else:
        res.update(
            decision="NO_MATCH",
            matched_username=None,
            matched_id=None,
            review_candidate=None,
            reason="All remaining candidates were rejected by manual review or did not qualify.",
        )
    if res.get("source_status") == "NOT_FOUND" and res["decision"] != "MATCH":
        # a rejected same-name account still exists; it is simply not this creator
        res["target_status"] = "EXISTS_UNVERIFIED" if cands else "NOT_FOUND"
    res["manual"] = True
    return res


def _display_from_candidate(c: dict[str, Any]) -> str:
    return written_id(str(c.get("platform")), str(c["username"]), c.get("display_name"))


# ---------------------------------------------------------------------------------------
# Matching rules (applied last, to every resolution and every platform pair).
#
# Source account exists. A candidate on the other platform is a "rule hit" when it has
#   * the exact same channel name, or
#   * the same profile picture (judged on the picture's subject, not its background), or
#   * exactly the same bio.
# A rule hit is a MATCH only if nothing contradicts it: a different (specific) category,
# a different broadcast language, a language that does not fit the sheet's country,
# different profile pictures, or a link to a different account. Two rule hits together
# (e.g. same name AND same picture) outweigh a category/language/country difference, but
# never a link to a different account. Contradicted hits, two equally good accounts, and
# strong near misses without a rule hit (e.g. the same Instagram) go to REVIEW: nothing is
# written to the sheet until a human confirms. Everything else: no account.
#
# Source account missing. A same-name account on the other platform is the MATCH, unless
# its language does not fit the sheet's country (then REVIEW).
# ---------------------------------------------------------------------------------------
_NAME_SEPARATORS = re.compile(r"[\s._-]+")
RULES = ("exact same name", "same profile picture", "exact same bio", "same name before a rename")


def _same_name(a: Any, b: Any) -> bool:
    a, b = str(a or "").strip().lower(), str(b or "").strip().lower()
    return bool(a) and _NAME_SEPARATORS.sub("_", a) == _NAME_SEPARATORS.sub("_", b)


def _same_bio(a: Any, b: Any) -> bool:
    a, b = " ".join(str(a or "").split()), " ".join(str(b or "").split())
    return bool(a) and a == b


def _signal_strengths(candidate: dict[str, Any]) -> dict[str, str]:
    return {str(s.get("name")): str(s.get("strength")) for s in candidate.get("signals") or []}


def rule_hits(source: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Every rule that makes ``candidate`` look like the same creator as ``source``."""
    hits = []
    # channel names (handles); "foo_bar" and Kick's slug "foo-bar" are the same name
    if _same_name(source.get("username"), candidate.get("username")):
        hits.append(RULES[0])
    # STRONG = same picture after border/background trimming and not a generic/default image
    if _signal_strengths(candidate).get("profile_image") == Strength.STRONG.value:
        hits.append(RULES[1])
    if _same_bio(source.get("description"), candidate.get("description")) or _same_bio(
        source.get("extra_bio"), candidate.get("description")
    ):
        hits.append(RULES[2])
    # a channel renamed on either side (Streams Charts) still had the other one's name
    names_a = [source.get("username"), *(source.get("former_names") or [])]
    names_b = [candidate.get("username"), *(candidate.get("former_names") or [])]
    if RULES[0] not in hits and any(_same_name(a, b) for a in names_a for b in names_b):
        hits.append(RULES[3])
    return hits


def rule_match(source: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    hits = rule_hits(source, candidate)
    return hits[0] if hits else None


def contradictions(
    source: dict[str, Any], candidate: dict[str, Any], country: str | None, hits: list[str]
) -> list[str]:
    """Category / language / country / picture / link evidence against ``candidate``."""
    out: list[str] = []
    ca = str(source.get("category") or "").strip().casefold()
    cb = str(candidate.get("category") or "").strip().casefold()
    if ca and cb and ca != cb and ca not in GENERIC_CATEGORIES and cb not in GENERIC_CATEGORIES:
        out.append(f"different category ({source.get('category')} / {candidate.get('category')})")
    la, lb = normalize_language(source.get("language")), normalize_language(candidate.get("language"))
    if la and lb and la != lb:
        out.append(f"different language ({la} / {lb})")
    langs = COUNTRY_LANGUAGES.get(fold_accents(country or "").casefold().strip())
    if langs and lb and lb not in langs:
        out.append(f"streams in {lb}, but the sheet says {country}")
    strengths = _signal_strengths(candidate)
    if RULES[1] not in hits and strengths.get("profile_image") == Strength.NEGATIVE.value:
        out.append("different profile pictures")
    if strengths.get("cross_link") == Strength.CONFLICT.value:
        out.append("links to a different account")
    if candidate.get("rename_confirmed") is False:
        out.append("its rename could not be confirmed by the channel ID")
    return out


def _decide(res: dict[str, Any], live: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None, str]:
    """(decision, candidate, reason) for a source account that exists."""
    source = res.get("source_profile") or {}
    country = res.get("country")
    matches: list[tuple[dict[str, Any], list[str]]] = []
    doubtful: list[tuple[dict[str, Any], list[str], list[str]]] = []
    for c in live:
        hits = rule_hits(source, c)
        if not hits:
            continue
        problems = contradictions(source, c, country, hits)
        linked_elsewhere = "links to a different account" in problems
        if not linked_elsewhere and (len(hits) >= 2 or not problems):
            matches.append((c, hits))
        else:
            doubtful.append((c, hits, problems))
    matches.sort(key=lambda m: (-len(m[1]), RULES.index(m[1][0])))
    if len(matches) == 1 or (len(matches) > 1 and len(matches[0][1]) > len(matches[1][1])):
        c, hits = matches[0]
        return "MATCH", c, " + ".join(hits)
    if matches:
        names = ", ".join(m[0]["username"] for m in matches[:3])
        return "REVIEW", matches[0][0], f"several accounts fit equally well ({names}); please choose"
    if doubtful:
        c, hits, problems = max(doubtful, key=lambda d: len(d[1]))
        return "REVIEW", c, f"{' + '.join(hits)}, but {'; '.join(problems)}"
    near = [c for c in live if c.get("decision") in ("MATCH", "REVIEW")]
    if near:
        c = max(near, key=lambda c: c.get("confidence") or 0.0)
        return "REVIEW", c, f"near miss (no exact name, picture or bio): {c.get('reason') or ''}".strip()
    return "NO_MATCH", None, ""


def apply_match_rules(resolution: dict[str, Any]) -> dict[str, Any]:
    """Final decision from the matching rules above. A human confirmation always stands;
    incomplete stored evidence (no engine decision) is left for the caller to reject."""
    if resolution.get("decision") is None or (
        resolution.get("manual") and resolution.get("decision") == "MATCH"
    ):
        return resolution
    res = dict(resolution)
    cands = [dict(c) for c in res.get("candidates") or []]
    res["candidates"] = cands
    live = [c for c in cands if c.get("username") and c.get("manual_verdict") != "REJECTED"]
    src_pf, tgt_pf = res.get("source_platform"), res.get("target_platform")
    if res.get("source_status") == "NOT_FOUND":
        best = live[0] if live else None
        problems = contradictions({}, best, res.get("country"), [RULES[0]]) if best else []
        decision = ("REVIEW" if problems else "MATCH") if best else "NO_MATCH"
        renamed = bool(best and best.get("former_names"))
        why = (
            f"source {src_pf} account does not exist; "
            + (
                f"the {tgt_pf} channel had the same name before a rename (Streams Charts)"
                if renamed
                else f"same-name {tgt_pf} account found"
            )
            + (f", but {'; '.join(problems)}" if problems else "")
        )
        res["target_status"] = (
            "VERIFIED" if decision == "MATCH" else ("EXISTS_UNVERIFIED" if cands else "NOT_FOUND")
        )
    else:
        decision, best, why = _decide(res, live)
    if decision == "MATCH" and best is not None:
        res.update(
            decision="MATCH",
            matched_username=best["username"],
            matched_id=_display_from_candidate(best),
            review_candidate=None,
            reason=f"Matched {tgt_pf}/{best['username']}: {why}.",
        )
    elif decision == "REVIEW" and best is not None:
        best["decision"] = "REVIEW"  # shown on the Review page
        res.update(
            decision="REVIEW",
            matched_username=None,
            matched_id=None,
            review_candidate=best["username"],
            reason=f"Needs review - {tgt_pf}/{best['username']}: {why}.",
        )
    else:
        res.update(
            decision="NO_MATCH",
            matched_username=None,
            matched_id=None,
            review_candidate=None,
            reason=(
                f"No {tgt_pf} account with the exact same name, profile picture or bio."
                if res.get("source_status") == "EXISTS"
                else f"Source {src_pf} account does not exist and no same-name {tgt_pf} account exists."
            ),
        )
    if res.get("renamed_source"):
        r = res["renamed_source"]
        res["reason"] = f"{res['reason']} (The {src_pf} channel {r['from']} is now called {r['to']}.)"
    if res.get("renamed_to_not_found"):
        res["reason"] = (
            f"{res['reason']} (renamed_to {res['renamed_to_not_found']!r}: no such {src_pf} channel.)"
        )
    return res
