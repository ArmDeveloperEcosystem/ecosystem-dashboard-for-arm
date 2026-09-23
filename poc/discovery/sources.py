"""Official GitHub and Docker Hub metadata collectors."""

from __future__ import annotations

import base64
import re
from urllib.parse import quote

from .evidence import classify_assets, classify_platforms, manifest_platforms
from .http import CollectionError, github_pages


def evidence(url, kind, excerpt, **extra):
    return {"url": url, "kind": kind, "excerpt": str(excerpt)[:2400], **extra}


def unknown(candidate, reason, failures=None):
    return {
        "candidate_id": candidate["id"],
        "name": candidate["name"],
        "source": candidate["source"],
        "status": "unknown",
        "scope": candidate.get("scope", "Selected repository release or container tag"),
        "reason": reason,
        "evidence": [],
        "failures": failures or [],
        "metadata": {},
    }


def github_collect(http, candidate, limits):
    repo = candidate["name"]
    base = f"https://api.github.com/repos/{repo}"
    result = unknown(candidate, "No release evidence could be established.")
    meta, _ = http.get(base)
    if not isinstance(meta, dict):
        raise CollectionError("Unexpected GitHub repository metadata shape")
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
    result["evidence"].append(
        evidence(
            f"https://github.com/{repo}",
            "repository_metadata",
            f"Repository {repo}; stars={meta.get('stargazers_count')}; archived={meta.get('archived')}; topics={meta.get('topics', [])}",
        )
    )
    releases, complete, errors = github_pages(
        http,
        base + "/releases",
        limits["max_release_pages"],
        stop_when=lambda values: any(
            isinstance(r, dict) and not r.get("draft") and not r.get("prerelease")
            for r in values
        ),
    )
    result["failures"].extend(errors)
    stable = [
        r
        for r in releases
        if isinstance(r, dict) and not r.get("draft") and not r.get("prerelease")
    ]
    if not stable:
        result["scope"] = (
            f"{repo}: stable releases visible in the bounded GitHub API scan"
        )
        result["reason"] = (
            "No stable release was returned in the bounded scan; source/build support remains unassessed."
        )
        result["evidence"].append(
            evidence(
                base + "/releases",
                "release_inventory",
                f"Stable releases observed: 0; all scanned pages complete={complete}",
            )
        )
        return result
    # GitHub API order is documented as creation order, not semantic version order.
    release = stable[0]
    tag = str(release.get("tag_name", "untagged"))
    release_url = (
        release.get("html_url")
        or f"https://github.com/{repo}/releases/tag/{quote(tag, safe='')}"
    )
    result["scope"] = (
        f"{repo} release {tag}: published downloadable Linux binaries (first stable release in GitHub API order)"
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
        http, asset_url, limits["max_asset_pages"]
    )
    result["failures"].extend(asset_errors)
    result["status"], result["reason"] = classify_assets(assets, assets_complete)
    supported_artifacts = [
        a.get("name", "")
        for a in assets
        if classify_assets([a], True)[0] == "supported"
    ]
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
            + "; ".join(str(a.get("name", "")) for a in assets),
            asset_names=[a.get("name") for a in assets],
            complete=assets_complete,
        )
    )
    # Individual named Linux assets get exact authoritative citations; no bytes run or downloaded.
    for asset in assets:
        name = str(asset.get("name", ""))
        if name in supported_artifacts:
            result["evidence"].append(
                evidence(
                    asset.get("browser_download_url") or asset_url,
                    "release_artifact",
                    name,
                    digest=asset.get("digest"),
                    size=asset.get("size"),
                )
            )
    try:
        readme, _ = http.get(base + "/readme", params={"ref": tag})
        if readme.get("encoding") == "base64":
            content = base64.b64decode(
                readme.get("content", ""), validate=False
            ).decode("utf-8", errors="replace")
            lines = content.splitlines()
            chosen = [
                line[:800]
                for line in lines
                if re.search(r"arm64|aarch64|architectur|linux", line, re.I)
            ][:8]
            result["evidence"].append(
                evidence(
                    readme.get("html_url")
                    or f"https://github.com/{repo}/tree/{quote(tag, safe='')}",
                    "official_readme",
                    "\n".join(chosen)
                    if chosen
                    else "No Linux/Arm64 architecture statement was found by the bounded README keyword extraction.",
                    tag=tag,
                )
            )
    except (CollectionError, ValueError, AttributeError) as exc:
        result["failures"].append(
            "Optional release-pinned README unavailable: " + str(exc)
        )
    return result


def _docker_manifest(http, repo, tag):
    token_data, _ = http.get(
        "https://auth.docker.io/token",
        params={"service": "registry.docker.io", "scope": f"repository:{repo}:pull"},
    )
    token = token_data.get("token") or token_data.get("access_token")
    if not token:
        raise CollectionError("Public registry token response did not include a token")
    base = f"https://registry-1.docker.io/v2/{repo}"
    manifest_url = base + "/manifests/" + quote(tag, safe="")
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": ", ".join(
            (
                "application/vnd.oci.image.index.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json",
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.v2+json",
            )
        ),
    }
    manifest, response_headers = http.get(manifest_url, headers=headers)
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
    if not isinstance(manifest.get("manifests"), list) and manifest.get(
        "config", {}
    ).get("digest"):
        digest = manifest["config"]["digest"]
        if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
            raise CollectionError("Unsupported or invalid manifest config digest")
        config_url = base + "/blobs/" + digest
        config, _ = http.get(config_url, headers=headers)
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
                if not p.get("attestation")
            )
            or "not established"
        )
        + f"; explicitly labeled attestation descriptors: {sum(bool(p.get('attestation')) for p in platforms)}; inventory complete={complete}."
    )
    return platforms, complete, ev


def dockerhub_collect(http, candidate, limits):
    repo, tag = candidate["name"], candidate.get("tag", "latest")
    namespace, image_name = repo.split("/", 1)
    url = f"https://hub.docker.com/v2/namespaces/{namespace}/repositories/{image_name}/tags/{quote(tag, safe='')}"
    result = unknown(candidate, "No container platform evidence could be established.")
    result["scope"] = (
        f"Docker Hub {repo}:{tag}: runtime platform inventory for this exact tag"
    )
    result["metadata"] = {"tag": tag}
    platforms, complete = [], False
    try:
        data, _ = http.get(url)
        images = data.get("images")
        if isinstance(images, list):
            platforms = [
                {
                    "os": p.get("os"),
                    "architecture": p.get("architecture"),
                    "variant": p.get("variant"),
                    "digest": p.get("digest"),
                }
                for p in images
            ]
            # Unknown/unknown descriptors may be attestations but Hub does not prove that.
            complete = bool(platforms) and all(
                p.get("os") not in {None, "", "unknown"}
                and p.get("architecture") not in {None, "", "unknown"}
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
    return result


def discover_github(http, config, limits):
    """A bounded repository search; search omission never implies absence."""
    found, failures, skips = [], [], []
    for query in config.get("github_queries", [])[: limits["max_queries"]]:
        remaining = limits["max_discovered"] - len(found)
        if remaining <= 0:
            skips.append(
                {
                    "source": "github_search",
                    "reason": "Discovery candidate limit reached",
                }
            )
            break
        q = f"{query} stars:>={config.get('min_stars', 500)} archived:false fork:false"
        rows, complete, errs = github_pages(
            http,
            "https://api.github.com/search/repositories",
            limits["max_search_pages"],
            params={
                "q": q,
                "sort": "stars",
                "order": "desc",
                "per_page": min(remaining, 100),
            },
            items_key="items",
            stop_after=remaining,
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
        for row in rows[:remaining]:
            if row.get("full_name"):
                found.append(
                    {"source": "github", "name": row["full_name"], "discovery_query": q}
                )
    return found, failures, skips
