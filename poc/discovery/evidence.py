"""Conservative evidence rules. These verify distribution metadata, not execution."""

from __future__ import annotations

import re

ARM64 = re.compile(r"(?:^|[^a-z0-9])(?:aarch64|arm64)(?:[^a-z0-9]|$)")
OTHER_ARCH = re.compile(
    r"(?:^|[^a-z0-9])(?:amd64|x86_64|x64|386|i386|i686|armv[5-7][a-z]*|armhf|ppc64le|s390x|riscv64)(?:[^a-z0-9]|$)"
)
LINUX = re.compile(r"(?:^|[^a-z0-9])linux(?:[^a-z0-9]|$)")
OTHER_OS = re.compile(
    r"(?:^|[^a-z0-9])(?:darwin|windows|win32|win64|macos|osx|freebsd|openbsd|netbsd|android|ios)(?:[^a-z0-9]|$)"
)
ANCILLARY = re.compile(
    r"(?:\.(?:asc|minisig|sig|sigstore|sha\d*|md5|txt|jsonl?|pem|pub|crt|sum|spdx|xml|md|rst|html?|pdf|ya?ml)$|checksum|sha256sum|sha512sum|sbom|provenance|attestation|(?:^|[-_.])(?:source|sources|src)(?:[-_.]|$))"
)


def assess_asset(asset: object) -> tuple[str, str]:
    """Describe one inventory entry without inferring component-family gaps."""
    if not isinstance(asset, dict):
        return "malformed", "Asset metadata is not an object."
    if not isinstance(asset.get("name"), str) or not asset["name"]:
        return "malformed", "Asset name is missing or is not a nonempty string."
    name = asset["name"].lower()
    if ANCILLARY.search(name) or asset.get("content_type") in (
        "text/plain",
        "text/html",
        "application/json",
        "application/pdf",
    ):
        return "excluded", "Ancillary, source, or documentation asset."
    if OTHER_OS.search(name) and not LINUX.search(name):
        return "excluded", "Asset explicitly names a non-Linux operating system."
    if OTHER_OS.search(name) or (ARM64.search(name) and OTHER_ARCH.search(name)):
        return "ambiguous", "Asset names contradictory platform or architecture labels."
    if asset.get("state", "uploaded") != "uploaded":
        return "ambiguous", "Asset upload is not complete."
    if "size" in asset and (
        not isinstance(asset["size"], int)
        or isinstance(asset["size"], bool)
        or asset["size"] <= 0
    ):
        return (
            "malformed",
            "Asset size does not establish a nonempty uploaded artifact.",
        )
    if LINUX.search(name) and ARM64.search(name):
        return (
            "supported",
            "Uploaded artifact explicitly names Linux and Arm64/aarch64.",
        )
    if LINUX.search(name) and OTHER_ARCH.search(name):
        return (
            "other_linux_binary",
            "Asset explicitly names Linux and another architecture.",
        )
    return (
        "ambiguous",
        "Operating system and architecture could not be established by the configured filename rules.",
    )


def classify_assets(assets: list[dict], complete: bool) -> tuple[str, str]:
    """An absence finding requires an exhaustive, unambiguous binary inventory."""
    if not isinstance(assets, list):
        return "unknown", "The release asset inventory has an unexpected shape."
    assessments = [assess_asset(asset)[0] for asset in assets]
    if "supported" in assessments:
        return (
            "supported",
            "At least one uploaded artifact published by the selected repository explicitly names Linux and Arm64/aarch64. This verifies that advertised artifact, not every component or runtime compatibility.",
        )
    ambiguous = any(value in {"ambiguous", "malformed"} for value in assessments)
    if not complete:
        return (
            "unknown",
            "The release asset inventory is incomplete; absence of a Linux Arm64 artifact cannot be established.",
        )
    if "other_linux_binary" in assessments and not ambiguous:
        return (
            "gap",
            "The complete published asset inventory contains Linux binaries for other architectures but no explicitly named Linux Arm64 binary. Scope is this release's downloadable artifacts only.",
        )
    if ambiguous:
        return (
            "unknown",
            "Asset names do not fully specify operating system and architecture; Linux Arm64 availability cannot be established.",
        )
    return (
        "unknown",
        "No relevant Linux binary distribution is established by this release's asset inventory.",
    )


def classify_platforms(platforms: list[dict], complete: bool) -> tuple[str, str]:
    """Never conflate arm/v7, Darwin Arm64, or Windows Arm64 with Linux Arm64."""
    if not isinstance(platforms, list):
        return "unknown", "Container platform metadata has an unexpected shape."
    # Preserve malformed records as unknown descriptors; dropping them could
    # turn an incomplete inventory into a false absence finding.
    platforms = [p if isinstance(p, dict) else {} for p in platforms]
    runtime = [
        {
            **p,
            "os": str(p.get("os") or "").strip().lower(),
            "architecture": str(p.get("architecture") or "").strip().lower(),
        }
        for p in platforms
        if not p.get("attestation") and not p.get("non_runtime_artifact")
    ]
    if any(
        p["os"] == "linux" and p["architecture"] in {"arm64", "aarch64"}
        for p in runtime
    ):
        return (
            "supported",
            "Authoritative platform metadata explicitly includes linux/arm64 for this exact container tag.",
        )
    recognized = {
        "amd64",
        "x86_64",
        "386",
        "arm",
        "arm64",
        "aarch64",
        "ppc64le",
        "ppc64",
        "s390x",
        "riscv64",
        "mips",
        "mipsle",
        "mips64",
        "mips64le",
        "loong64",
    }
    recognized_os = {
        "linux",
        "windows",
        "darwin",
        "freebsd",
        "openbsd",
        "netbsd",
        "dragonfly",
        "solaris",
        "illumos",
        "android",
        "ios",
        "aix",
        "plan9",
    }
    fully_described = all(
        p["os"] in recognized_os and p["architecture"] in recognized for p in runtime
    )
    if complete and runtime and fully_described:
        return (
            "gap",
            "The complete runtime platform inventory for this tag does not include linux/arm64. This does not establish a project-wide support gap.",
        )
    return (
        "unknown",
        "Container platform metadata is missing or incomplete; lack of a Linux Arm64 descriptor is not proof of a support gap.",
    )


def manifest_platforms(
    manifest: dict, config: dict | None = None
) -> tuple[list[dict], bool]:
    """OCI single-platform image manifests require the referenced config blob."""
    if not isinstance(manifest, dict):
        return [], False
    if manifest.get("artifactType") or manifest.get("schemaVersion", 2) != 2:
        return [], False
    image_media_types = {
        None,
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    }
    if (
        not isinstance(manifest.get("mediaType"), (str, type(None)))
        or manifest.get("mediaType") not in image_media_types
    ):
        return [], False
    if isinstance(manifest.get("manifests"), list):
        values = []
        for item in manifest["manifests"]:
            if not isinstance(item, dict):
                values.append({})
                continue
            annotations = item.get("annotations") or {}
            if not isinstance(annotations, dict):
                values.append({})
            elif annotations.get("vnd.docker.reference.type") == "attestation-manifest":
                values.append({"attestation": True, "digest": item.get("digest")})
            elif item.get("artifactType"):
                values.append(
                    {"non_runtime_artifact": True, "digest": item.get("digest")}
                )
            elif (
                not isinstance(item.get("mediaType"), (str, type(None)))
                or item.get("mediaType") not in image_media_types
            ):
                values.append({})
            else:
                platform = item.get("platform")
                values.append(
                    {
                        **(platform if isinstance(platform, dict) else {}),
                        "digest": item.get("digest"),
                    }
                )
        return values, bool(values)
    descriptor = manifest.get("config")
    if isinstance(descriptor, dict) and isinstance(config, dict) and config:
        config_type = descriptor.get("mediaType")
        if config_type not in (
            None,
            "application/vnd.oci.image.config.v1+json",
            "application/vnd.docker.container.image.v1+json",
        ):
            return [], False
        return [
            {
                "os": config.get("os"),
                "architecture": config.get("architecture"),
                "variant": config.get("variant"),
                "digest": descriptor.get("digest"),
            }
        ], True
    return [], False
