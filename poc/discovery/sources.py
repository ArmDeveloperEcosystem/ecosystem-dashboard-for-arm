"""Official GitHub and Docker Hub metadata collectors."""

from __future__ import annotations

import base64
import posixpath
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlparse

from .evidence import (
    assess_asset,
    classify_assets,
    classify_platforms,
    manifest_platforms,
)
from .http import CollectionError, github_pages
from .identity import normalize_github_name


def evidence(url, kind, excerpt, **extra):
    return {"url": url, "kind": kind, "excerpt": str(excerpt)[:2400], **extra}


def _github_link(value, repo, fallback):
    """Keep citations on the selected official repository, even with bad metadata."""
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f\\]", value):
        return fallback
    try:
        parsed = urlparse(value)
        path = posixpath.normpath(unquote(parsed.path))
        if (
            parsed.scheme == "https"
            and parsed.netloc.lower() in {"github.com", "github.com:443"}
            and not re.search(r"[\x00-\x20\x7f\\]", path)
            and (path.lower() + "/").startswith("/" + repo.lower() + "/")
        ):
            return value
    except ValueError:
        pass
    return fallback


def popularity(name, value, unit, period, url):
    return {
        "name": name,
        "value": value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None,
        "unit": unit,
        "period": period,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": url,
    }


def unknown(candidate, reason, failures=None):
    return {
        "candidate_id": candidate["id"],
        "name": candidate["name"],
        "source": candidate["source"],
        "status": "unknown",
        "scope": (
            f"Docker Hub {candidate['name']}:{candidate.get('tag', 'latest')}: selected container tag"
            if candidate["source"] == "dockerhub"
            else f"{candidate['name']}: selected repository release"
        ),
        "reason": reason,
        "evidence": [],
        "failures": failures or [],
        "metadata": {},
        "popularity_signals": [],
    }


def _collect_readme(http, repo, result, ref=None, *, release=False):
    """README context never promotes a distribution verdict. Retain blob identity."""
    base = f"https://api.github.com/repos/{repo}"
    context = "release tag" if release else "repository default branch"
    try:
        readme, _ = http.get(base + "/readme", params={"ref": ref} if ref else None)
        if not isinstance(readme, dict) or readme.get("encoding") != "base64":
            raise CollectionError("Unexpected README content metadata")
        content = base64.b64decode(readme.get("content", ""), validate=False).decode(
            "utf-8", errors="replace"
        )
        chosen = [
            line[:800]
            for line in content.splitlines()
            if re.search(r"arm64|aarch64|architectur|linux", line, re.IGNORECASE)
        ][:8]
        sha = readme.get("sha")
        valid_sha = isinstance(sha, str) and re.fullmatch(r"[a-fA-F0-9]{40}", sha)
        url = (
            base + "/git/blobs/" + sha
            if valid_sha
            else _github_link(
                readme.get("html_url"), repo, f"https://github.com/{repo}"
            )
        )
        result["evidence"].append(
            evidence(
                url,
                "official_readme",
                "\n".join(chosen)
                if chosen
                else "No Linux/Arm64 architecture statement was found by the bounded README keyword extraction.",
                context=context,
                ref=ref,
                tag=ref if release else None,
                blob_sha=sha if valid_sha else None,
                collected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )
    except (CollectionError, ValueError, TypeError) as exc:
        result["failures"].append(f"Optional {context} README unavailable: {exc}")


def _github_coverage(assets, complete, asset_url, repo):
    """Retain bounded inventory context separately from the three verdicts."""
    supported, remaining, reasons = [], [], []
    if not complete:
        reasons.append("The selected release's asset inventory is incomplete.")
    for asset in assets:
        assessment, reason = assess_asset(asset)
        if assessment == "supported":
            supported.append(asset["name"])
            continue
        item = {
            key: asset.get(key) if isinstance(asset, dict) else None
            for key in ("name", "size", "state", "content_type")
        }
        item.update(
            asset_id=asset.get("id") if isinstance(asset, dict) else None,
            url=_github_link(asset.get("browser_download_url"), repo, asset_url)
            if isinstance(asset, dict)
            else asset_url,
            assessment=assessment,
            reason=reason,
        )
        if assessment == "malformed":
            item["raw_metadata"] = asset
        remaining.append(item)
    for assessment in ("malformed", "ambiguous"):
        count = sum(item["assessment"] == assessment for item in remaining)
        if count:
            reasons.append(
                f"{count} remaining asset record(s) have {assessment} distribution metadata; see the inventory and evidence."
            )
    return {
        "kind": "github_release_assets",
        "inventory_complete": complete,
        "inventory_count": len(assets),
        "supported_artifacts": supported,
        "remaining_inventory": remaining,
        "review_required": bool(reasons),
        "review_reasons": reasons,
        "evidence_urls": [asset_url],
        "limitations": [
            "Advertised distribution metadata does not verify runtime compatibility or source builds.",
            "Component-family completeness is not inferred from artifact names; other distributions remain unassessed.",
        ],
    }


def github_collect(http, candidate, limits):
    repo = candidate["name"]
    base = f"https://api.github.com/repos/{repo}"
    result = unknown(candidate, "No release evidence could be established.")
    meta, _ = http.get(base)
    if not isinstance(meta, dict):
        raise CollectionError("Unexpected GitHub repository metadata shape")
    if meta.get("private") is True or meta.get("visibility") not in (None, "public"):
        raise CollectionError(
            "Repository is not public; private/internal repository evidence is outside this PoC"
        )
    if meta.get("full_name") and str(meta["full_name"]).lower() != repo.lower():
        raise CollectionError(
            "Repository identity does not match the selected candidate"
        )
    result["metadata"] = {
        k: meta.get(k)
        for k in (
            "description",
            "stargazers_count",
            "topics",
            "archived",
            "fork",
            "updated_at",
            "license",
        )
    }
    result["popularity_signals"] = [
        popularity(
            "GitHub stars", meta.get("stargazers_count"), "stars", "current total", base
        )
    ]
    result["evidence"].append(
        evidence(
            f"https://github.com/{repo}",
            "repository_metadata",
            f"Repository {repo}; stars={meta.get('stargazers_count')}; archived={meta.get('archived')}; topics={meta.get('topics', [])}",
        )
    )
    repository_id = meta.get("id")
    canonical_prefix = (
        f"/repositories/{repository_id}"
        if isinstance(repository_id, int) and not isinstance(repository_id, bool)
        else None
    )
    latest_url = base + "/releases/latest"
    result["metadata"]["release_selection"] = "github_latest_release"
    result["metadata"]["release_selection_url"] = latest_url
    result["metadata"]["release_selection_limitations"] = (
        "GitHub's latest published full release does not establish maintenance "
        "status, greatest semantic version or coverage of every supported release line."
    )
    try:
        release, _ = http.get(latest_url)
        if not isinstance(release, dict):
            raise CollectionError("Unexpected GitHub latest-release metadata shape")
        if any(
            key in release and not isinstance(release[key], bool)
            for key in ("draft", "prerelease")
        ):
            raise CollectionError(
                "GitHub latest-release publication flags are malformed"
            )
        if release.get("draft") or release.get("prerelease"):
            raise CollectionError(
                "GitHub latest-release metadata is not a published full release"
            )
        if (
            not isinstance(release.get("tag_name"), str)
            or not release["tag_name"].strip()
        ):
            raise CollectionError(
                "GitHub latest-release metadata has no valid tag name"
            )
    except CollectionError as exc:
        if exc.status_code == 404:
            result["metadata"]["latest_release_response_status"] = 404
        else:
            result["failures"].append(f"Latest published release unavailable: {exc}")
        result["scope"] = f"{repo}: GitHub latest published full release"
        result["reason"] = (
            "A valid latest published full release could not be established; "
            "older releases were not substituted. Source/build support remains unassessed."
        )
        result["evidence"].append(
            evidence(
                latest_url,
                "release_selection",
                "No valid latest published full release was established; no historical-release fallback was used.",
            )
        )
        result["assessment_coverage"] = {
            "kind": "github_latest_release",
            "inventory_complete": False,
            "inventory_count": 0,
            "supported_artifacts": [],
            "remaining_inventory": [],
            "review_required": True,
            "review_reasons": [
                "The latest published full release could not be established; its artifact inventory remains unassessed."
            ],
            "evidence_urls": [latest_url],
            "limitations": [
                "No release was selected; downloadable artifacts, source builds and runtime compatibility remain unassessed.",
                result["metadata"]["release_selection_limitations"],
            ],
        }
        _collect_readme(http, repo, result, meta.get("default_branch"))
        return result
    if not isinstance(release.get("id"), int) or isinstance(release.get("id"), bool):
        result["reason"] = (
            "The selected release has no valid release ID; its asset inventory cannot be verified."
        )
        result["failures"].append("Malformed release metadata")
        result["assessment_coverage"] = {
            "kind": "github_release_assets",
            "inventory_complete": False,
            "inventory_count": 0,
            "supported_artifacts": [],
            "remaining_inventory": [],
            "review_required": True,
            "review_reasons": [
                "The selected release lacks a valid release ID; its artifact inventory cannot be read."
            ],
            "evidence_urls": [latest_url],
            "limitations": [
                "Source builds and runtime compatibility remain unassessed."
            ],
        }
        return result
    tag = str(release.get("tag_name", "untagged"))
    try:
        release_fallback = (
            f"https://github.com/{repo}/releases/tag/{quote(tag, safe='')}"
        )
    except UnicodeEncodeError:
        # Preserve the original tag. An invalid Unicode tag cannot safely form
        # a web URL, so cite the already selected release by its numeric ID.
        release_fallback = base + f"/releases/{release['id']}"
    release_url = _github_link(
        release.get("html_url"),
        repo,
        release_fallback,
    )
    result["scope"] = (
        f"{repo} release {tag}: published downloadable Linux binaries (GitHub latest published full release)"
    )
    result["metadata"].update(
        {
            "release_tag": tag,
            "release_id": release.get("id"),
            "release_published_at": release.get("published_at"),
        }
    )
    result["evidence"].append(
        evidence(
            release_url,
            "release_notes",
            release.get("body") or "This release has no release notes.",
            tag=tag,
        )
    )
    asset_url = base + f"/releases/{release['id']}/assets"
    assets, assets_complete, asset_errors = github_pages(
        http,
        asset_url,
        limits["max_asset_pages"],
        alternate_paths=[canonical_prefix + f"/releases/{release['id']}/assets"]
        if canonical_prefix
        else [],
    )
    result["failures"].extend(asset_errors)
    result["status"], result["reason"] = classify_assets(assets, assets_complete)
    result["assessment_coverage"] = _github_coverage(
        assets, assets_complete, asset_url, repo
    )
    supported_artifacts = result["assessment_coverage"]["supported_artifacts"]
    result["metadata"]["supported_artifacts"] = supported_artifacts
    if result["status"] == "supported":
        result["scope"] = (
            f"{repo} release {tag}: advertised Linux Arm64 artifacts "
            + ", ".join(supported_artifacts)
            + "; other components and runtime compatibility unassessed"
        )
    result["metadata"]["asset_inventory_complete"] = assets_complete
    result["metadata"]["asset_count"] = len(assets)
    result["evidence"].append(
        evidence(
            asset_url,
            "release_asset_inventory",
            f"Complete={assets_complete}; assets={len(assets)}; names="
            + "; ".join(
                str(a.get("name", "")) if isinstance(a, dict) else "malformed asset"
                for a in assets
            ),
            asset_names=[
                a.get("name") if isinstance(a, dict) else None for a in assets
            ],
            complete=assets_complete,
        )
    )
    # Individual named Linux assets get exact authoritative citations; no bytes run or downloaded.
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", ""))
        if name in supported_artifacts:
            result["evidence"].append(
                evidence(
                    _github_link(asset.get("browser_download_url"), repo, asset_url),
                    "release_artifact",
                    name,
                    digest=asset.get("digest"),
                    size=asset.get("size"),
                )
            )
    _collect_readme(http, repo, result, tag, release=True)
    return result


def _docker_manifest(http, repo, tag):
    token_data, _ = http.get(
        "https://auth.docker.io/token",
        params={"service": "registry.docker.io", "scope": f"repository:{repo}:pull"},
    )
    if not isinstance(token_data, dict):
        raise CollectionError("Unexpected public registry token response shape")
    token = token_data.get("token") or token_data.get("access_token")
    if not isinstance(token, str) or not token or re.search(r"[\x00-\x20\x7f]", token):
        raise CollectionError("Public registry token response did not include a token")
    base = f"https://registry-1.docker.io/v2/{repo}"
    manifest_url = base + "/manifests/" + quote(tag, safe="")
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": (
            "application/vnd.oci.image.index.v1+json, "
            "application/vnd.docker.distribution.manifest.list.v2+json, "
            "application/vnd.oci.image.manifest.v1+json, "
            "application/vnd.docker.distribution.manifest.v2+json"
        ),
    }
    manifest, response_headers = http.get(manifest_url, headers=headers)
    if not isinstance(manifest, dict):
        raise CollectionError("Unexpected OCI manifest metadata shape")
    config = None
    ev = [
        evidence(
            manifest_url,
            "oci_manifest",
            "Official registry manifest metadata",
            digest=response_headers.get("Docker-Content-Digest")
            or response_headers.get("docker-content-digest"),
            manifest=manifest,
        )
    ]
    descriptor = manifest.get("config")
    if (
        not manifest.get("artifactType")
        and not isinstance(manifest.get("manifests"), list)
        and isinstance(descriptor, dict)
        and descriptor.get("digest")
    ):
        digest = descriptor["digest"]
        if not isinstance(digest, str) or not re.fullmatch(
            r"sha256:[a-fA-F0-9]{64}", digest
        ):
            raise CollectionError("Unsupported or invalid manifest config digest")
        config_url = base + "/blobs/" + digest
        config, _ = http.get(config_url, headers=headers)
        if not isinstance(config, dict):
            raise CollectionError("Unexpected OCI image config metadata shape")
        ev.append(
            evidence(
                config_url,
                "oci_image_config",
                f"os={config.get('os')}; architecture={config.get('architecture')}",
                digest=digest,
            )
        )
    platforms, complete = manifest_platforms(manifest, config)
    ev[0]["excerpt"] = (
        "Runtime platforms: "
        + (
            "; ".join(
                f"{p.get('os') or 'missing'}/{p.get('architecture') or 'missing'}"
                for p in platforms
                if not p.get("attestation") and not p.get("non_runtime_artifact")
            )
            or "not established"
        )
        + f"; explicitly labeled attestation descriptors: {sum(bool(p.get('attestation')) for p in platforms)}; other non-runtime artifacts: {sum(bool(p.get('non_runtime_artifact')) for p in platforms)}; inventory complete={complete}."
    )
    return platforms, complete, ev


def dockerhub_collect(http, candidate, limits):
    repo, tag = candidate["name"], candidate.get("tag", "latest")
    namespace, image_name = repo.split("/", 1)
    repository_url = (
        f"https://hub.docker.com/v2/namespaces/{namespace}/repositories/{image_name}"
    )
    url = repository_url + f"/tags/{quote(tag, safe='')}"
    result = unknown(candidate, "No container platform evidence could be established.")
    result["scope"] = (
        f"Docker Hub {repo}:{tag}: runtime platform inventory for this exact tag"
    )
    result["metadata"] = {"tag": tag}
    repository = {}
    try:
        repository, _ = http.get(repository_url)
        if not isinstance(repository, dict):
            raise CollectionError("Unexpected Docker Hub repository metadata shape")
    except CollectionError as exc:
        repository = {}
        result["failures"].append(
            "Optional Docker Hub repository metadata: " + str(exc)
        )
    try:
        if repository.get("is_private") is True:
            raise CollectionError(
                "Private Docker Hub repository is outside this public-source PoC"
            )
        if (
            repository.get("namespace")
            and str(repository["namespace"]).lower() != namespace.lower()
        ):
            raise CollectionError(
                "Docker Hub namespace does not match the selected candidate"
            )
        if (
            repository.get("name")
            and str(repository["name"]).lower() != image_name.lower()
        ):
            raise CollectionError(
                "Docker Hub repository does not match the selected candidate"
            )
    except CollectionError as exc:
        return unknown(
            candidate,
            "The selected public repository identity could not be verified.",
            [str(exc)],
        )
    platforms, complete = [], False
    try:
        data, _ = http.get(url)
        if not isinstance(data, dict):
            raise CollectionError("Unexpected Docker Hub tag metadata shape")
        if data.get("name") is not None and data["name"] != tag:
            raise CollectionError(
                "Docker Hub tag metadata does not match the selected tag"
            )
        images = data.get("images")
        if isinstance(images, list):
            platforms = [
                {
                    "os": p.get("os"),
                    "architecture": p.get("architecture"),
                    "variant": p.get("variant"),
                    "digest": p.get("digest"),
                }
                if isinstance(p, dict)
                else {}
                for p in images
            ]
            # Unknown/unknown descriptors may be attestations but Hub does not prove that.
            complete = bool(platforms) and all(
                isinstance(p.get("os"), str)
                and p["os"].strip().lower() not in {"", "unknown"}
                and isinstance(p.get("architecture"), str)
                and p["architecture"].strip().lower() not in {"", "unknown"}
                for p in platforms
            )
        result["metadata"].update(
            {"tag_last_updated": data.get("last_updated"), "digest": data.get("digest")}
        )
        result["evidence"].append(
            evidence(
                url,
                "dockerhub_tag_platforms",
                "; ".join(
                    f"{p.get('os')}/{p.get('architecture')}/{p.get('variant') or '-'}"
                    for p in platforms
                )
                or "No image platform descriptors returned",
                platforms=platforms,
                complete=complete,
                tag=tag,
            )
        )
    except (CollectionError, AttributeError, TypeError) as exc:
        result["failures"].append(str(exc))
    status, reason = classify_platforms(platforms, complete)
    if status == "unknown" and limits.get("oci_fallback", True):
        try:
            platforms, complete, ev = _docker_manifest(http, repo, tag)
            result["evidence"].extend(ev)
            status, reason = classify_platforms(platforms, complete)
        except (CollectionError, AttributeError, TypeError) as exc:
            result["failures"].append("OCI metadata fallback: " + str(exc))
    result.update(status=status, reason=reason)
    result["metadata"].update(platforms=platforms, platform_inventory_complete=complete)
    if repository:
        fields = (
            "pull_count",
            "star_count",
            "description",
            "last_updated",
            "is_private",
            "is_official",
            "namespace",
            "repository_type",
        )
        result["metadata"].update({key: repository.get(key) for key in fields})
        # API affiliation is the caller's relation to a repository, not a
        # Verified Publisher / Sponsored Open Source badge.
        result["metadata"]["publisher_recognition"] = (
            "Docker Official Image"
            if namespace == "library"
            else "Not established by this metadata response"
        )
        result["evidence"].append(
            evidence(
                repository_url,
                "dockerhub_repository_metadata",
                f"Repository {repo}; cumulative pulls={repository.get('pull_count')}; stars={repository.get('star_count')}; publisher context={result['metadata']['publisher_recognition']}. Popularity and publisher context do not certify Arm64 support.",
            )
        )
    result["popularity_signals"] = [
        popularity(
            "Docker Hub pulls",
            repository.get("pull_count"),
            "pulls",
            "cumulative total; not unique deployments",
            repository_url,
        ),
        popularity(
            "Docker Hub stars",
            repository.get("star_count"),
            "stars",
            "current total",
            repository_url,
        ),
    ]
    return result


def discover_github(http, config, limits, known_ids=None):
    """A bounded repository search; search omission never implies absence."""
    found, failures, skips = [], [], []
    known = set()
    for identity in known_ids or ():
        if isinstance(identity, str) and identity.startswith("github:"):
            try:
                known.add("github:" + normalize_github_name(identity[7:]))
            except ValueError:
                pass
    seen, fetched, examined, excluded, deferred = set(), 0, 0, 0, 0
    source_limit = limits.get("max_source_records", 40)
    for query in config.get("github_queries", [])[: limits["max_queries"]]:
        if getattr(http, "requests_used", 0) >= limits.get(
            "max_requests", float("inf")
        ) or (
            hasattr(http, "started")
            and time.monotonic() - http.started
            >= limits.get("max_seconds", float("inf"))
        ):
            skips.append(
                {
                    "source": "github_search",
                    "reason": "Source request/time allowance exhausted; additional discovery deferred",
                }
            )
            break
        remaining = limits["max_discovered"] - len(found)
        if remaining <= 0:
            skips.append(
                {
                    "source": "github_search",
                    "reason": "Discovery candidate limit reached",
                }
            )
            break
        source_remaining = source_limit - fetched
        if source_remaining <= 0:
            skips.append(
                {
                    "source": "github_search",
                    "reason": "Source-record limit reached; additional discovery deferred",
                }
            )
            break
        q = f"{query} stars:>={config.get('min_stars', 500)} archived:false fork:false is:public"
        rows, complete, errs = github_pages(
            http,
            "https://api.github.com/search/repositories",
            limits["max_search_pages"],
            params={
                "q": q,
                "sort": "stars",
                "order": "desc",
                "per_page": min(source_remaining, 100),
            },
            items_key="items",
            stop_after=source_remaining,
            max_records=source_remaining,
        )
        failures.extend(
            {"source": "github_search", "query": q, "reason": err} for err in errs
        )
        if not complete:
            skips.append(
                {
                    "source": "github_search",
                    "query": q,
                    "reason": "Search limited to configured pages/candidate budget; not an exhaustive ecosystem census",
                }
            )
        fetched += len(rows)
        selected_rows = rows[:source_remaining]
        examined += len(selected_rows)
        for rank, row in enumerate(selected_rows, 1):
            if not isinstance(row, dict) or not isinstance(row.get("full_name"), str):
                excluded += 1
                continue
            try:
                name = normalize_github_name(row["full_name"])
            except ValueError:
                excluded += 1
                continue
            identity = "github:" + name
            if (
                identity in known
                or identity in seen
                or row.get("private") is True
                or row.get("visibility") not in (None, "public")
                or row.get("archived") is True
                or row.get("fork") is True
            ):
                excluded += 1
                continue
            seen.add(identity)
            if len(found) < limits["max_discovered"]:
                found.append(
                    {
                        "source": "github",
                        "name": row["full_name"],
                        "discovery_query": q,
                        "discovery_stars": row.get("stargazers_count"),
                        "discovery_rank": rank,
                    }
                )
            else:
                deferred += 1
    if deferred:
        skips.append(
            {
                "source": "github_search",
                "reason": "Additional unseen search results deferred by discovery candidate limit",
                "count": deferred,
            }
        )
    skips.append(
        {
            "source": "github_search",
            "reason": "Source records examined",
            "metric": "source_records_examined",
            "count": examined,
            "informational": True,
        }
    )
    skips.extend(
        {
            "source": "github_search",
            "reason": reason,
            "metric": metric,
            "count": count,
            "informational": True,
        }
        for reason, metric, count in (
            ("Source records fetched", "source_records_fetched", fetched),
            (
                "Discovery candidates selected",
                "discovery_candidates_selected",
                len(found),
            ),
        )
    )
    if excluded:
        skips.append(
            {
                "source": "github_search",
                "reason": "Known, duplicate, private, inactive or malformed search records excluded",
                "count": excluded,
            }
        )
    return found, failures, skips
