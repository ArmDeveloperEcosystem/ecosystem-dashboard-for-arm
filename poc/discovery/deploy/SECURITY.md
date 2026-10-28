# Image security validation

The implementation is ready for code review. **Production security acceptance
remains open:** the measured hardened image retains eight distinct HIGH advisory IDs that
need an operational security owner's disposition or further remediation. No
findings were suppressed and no risk waiver was granted.

## Current validation: October 7, 2026

The runtime base is now the official
[Python 3.12.15 security release](https://www.python.org/downloads/release/python-31215/),
using the verified multi-platform index
`sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`.
The Python ABI, hash-locked runtime wheels and deployment restrictions are
unchanged. CI uses the same Python patch release.

The October 7 Trivy database found three additional HIGH advisory IDs in a
fresh build of the previous pinned base. The supported base refresh provides
OpenSSL `3.5.7-1~deb13u3` and PCRE2 `10.46-1~deb13u3`, resolving those matches:
[CVE-2026-75804](https://security-tracker.debian.org/tracker/CVE-2026-75804),
[CVE-2026-84782](https://security-tracker.debian.org/tracker/CVE-2026-84782) and
[CVE-2026-103111](https://security-tracker.debian.org/tracker/CVE-2026-103111).
This also applies Python's September 30 security release; Python interpreter
coverage must not be inferred from the third-party wheel inventory alone.

Both images below were measured with the same fresh database, without
suppression or inventory changes:

| October 7 Debian result | Critical | High | Medium | Low | Unknown | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Previous base, source revision `6d8a263af` | 0 | 47 | 84 | 66 | 2 | 199 |
| Updated base and reviewed working tree | 0 | 40 | 57 | 60 | 2 | 159 |

- Previous-base image index: `sha256:aa5c65186d87f0a24068fc1716014b4e3dcc4e039f545f011bed1daf457b60eb`;
  scanned config digest: `sha256:34744d11237efe56b242d530d14bba58cf8da70654610e37c2844c809224bc4a`.
- Updated candidate image index: `sha256:f088a75c4975f0b6397583eb96dd6a8b438de3ca790ab3c62a4c86b6794b8866`;
  scanned config digest: `sha256:5ee06a51519dbd1b3e87ac93dadc4fe9a068e573b1979ddc5dcc18f2ebd2f389`.
  Its revision label explicitly identifies the reviewed working tree based on
  `6d8a263af44bee27827c1a82850cb0a118319316`; it is not a committed release image.
  The retained source-hash manifest records the exact copied inputs, including
  the release-inventory coverage refresh fix. Rebuild the final release revision and
  retain its own immutable image and scan before deployment.
- Scanner: the same checksum-verified Trivy 0.74.0 release recorded below;
  local executable bytes were also checked against the verified archive.
- Database: `ghcr.io/aquasecurity/trivy-db:2`, updated
  `2026-10-07T07:38:55.515026687Z`; candidate scan timestamp
  `2026-10-07T16:44:20-05:00`.
- Inventory: 86 Debian packages and nine Python packages. The candidate has
  72 distinct advisory IDs overall, including the same eight HIGH IDs listed
  below. None has a fixed Trixie version in this database. The complete JSON
  retains every severity and package record; the scan exits 1 for findings.
- No Python-package advisories were found. Fresh pip-audit 2.10.1 checks also
  found no known advisories for the runtime lock or build-only pip pin.
- Both images passed the existing native Arm64 default-command smoke with two
  persistent runs, UID 10001, a read-only root, dropped capabilities,
  `no-new-privileges` and network disabled. No source or model calls occurred.
- All 347 PoC discovery tests passed in a separate native Arm64 Python 3.12.15
  test image with network disabled. The production image's packaged Python
  source hashes match both the frozen snapshot and reviewed working tree;
  installer/test packages remain absent from the production image.

Raw builds, immutable image exports, complete scans, dependency audits, smoke
results and `final-context-hashes.json` are retained locally under ignored
`.poc/completion-20261007/runtime/`. The available `ecosystem-search` Colima
profile was used with an explicit Docker context. The default profile's
disk-in-use error was left unchanged; no VM deletion or forced unlock was used.
These measurements do not grant a residual-risk exception or production approval.

## Historical validation: September 24, 2026

- Baseline Linux Arm64 image at commit
  `ff2e0310983a03c48ec683d56019d94230aba701`:
  `sha256:0782987fae76dcf88312d5ee8b47f4fac94fb4006f51f47fb848f02cd55e9a52`.
- Isolated hardening probe derived from that exact baseline by normal removal
  of the unused `mount` package:
  `sha256:c7efc4cb51cfa7f73938976823aff286c4478d4b777fde2581768a52e9691bcf`.
  This is a measured experiment, not an approved production release. Rebuild
  and scan the final release commit; record its own image digest and results.
- Scanner: [Trivy 0.74.0 official immutable release](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0).
  The downloaded macOS Arm64 archive matched both its official checksum file
  and GitHub release asset digest:
  `1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11`.
- Database: `ghcr.io/aquasecurity/trivy-db:2`, updated
  `2026-09-24T13:23:01Z`; hardening scan timestamp
  `2026-09-24T22:47:30-05:00`.

The hardening scan inspected 86 Debian 13.7 packages and nine Python packages. These are
**package/advisory occurrences**, so one advisory can appear against several
binary packages built from the same source package.

| Measured result | Critical | High | Medium | Low | Unknown | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline Debian packages | 0 | 44 | 53 | 57 | 2 | 156 |
| Hardened Debian packages | 0 | 40 | 52 | 56 | 2 | 150 |
| Python packages | 0 | 0 | 0 | 0 | 0 | 0 |

There are 68 distinct advisory IDs overall; eight account for the 40 HIGH
occurrences. The database supplies no fixed Trixie version for these remaining
findings. Some severity ratings come from other vendors; package matching is
not proof of exploitability in this application.

The hardening removes four HIGH occurrences and the actual `mount`/`umount`
executables. It does not eliminate the underlying util-linux advisory IDs:
other packages from that source remain. No scan filters or inventory edits were
used to obtain the reduction.

## Remediation completed

The pinned base changed from Python 3.12.14 Bookworm to the verified Python
3.12.14 Trixie multi-platform index in [Dockerfile](Dockerfile). Compared with
the original image, this removed all five CRITICAL matches and reduced Debian
occurrences from 268 to 156. Debian tracks the prior
[SQLite](https://security-tracker.debian.org/tracker/CVE-2025-7458),
[Perl regular-expression](https://security-tracker.debian.org/tracker/CVE-2026-13221),
[Perl archive](https://security-tracker.debian.org/tracker/CVE-2026-42496),
[Perl 32-bit](https://security-tracker.debian.org/tracker/CVE-2026-8376) and
[zlib](https://security-tracker.debian.org/tracker/CVE-2023-45853) advisories as
fixed in Trixie.

The original image also retained pip 25.0.1 with six fixable advisories. The build
now installs hash-pinned pip 26.2, installs the locked runtime wheels, checks
dependencies, then removes pip and ensurepip from the runtime image. The final
scan contains neither installer. Separate pip-audit 2.10.1 checks against PyPI
found no known advisories in the nine runtime pins or the build-only pip pin.

The Dockerfile now removes the runtime-unused `mount` package using
`apt-get purge --yes mount`, then verifies dependencies with `apt-get check`
and the package database with `dpkg --audit`. The probe passed the native Arm64
default-command smoke test twice with persistent state, UID 10001, a read-only
root filesystem, no network, dropped capabilities and `no-new-privileges`.
No source requests or model calls occurred. `mount` and `umount` are absent;
`nsenter`, `infocmp` and Perl remain recorded in the inventory.

Further normal removal is constrained by Debian's Essential package dependency
graph. `util-linux`, `bsdutils`, `ncurses-bin` and `perl-base` are Essential;
the systemd/udev and ACL libraries are dependencies of Essential packages.
The build does not force removal, manually delete package records, import
testing/unstable packages or change distributions just to improve a scan.
Debian currently lists the [util-linux fix](https://security-tracker.debian.org/tracker/CVE-2026-76642),
[ACL fix](https://security-tracker.debian.org/tracker/CVE-2026-54369) and
[ncurses fix](https://security-tracker.debian.org/tracker/CVE-2025-69720)
in testing/unstable, with Trixie still affected. Follow supported stable updates
and retain the owner decision for residual findings.

## Remaining HIGH advisory applicability

All rows below have **no fixed Trixie package version listed** on the scan date.
The observations describe the inspected image and intended batch deployment;
they do not approve an exception to security policy.

| Advisory IDs | Installed packages / occurrences | Observed boundary |
| --- | --- | --- |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | util-linux source package 2.41.5-0+deb13u1; eight binary packages, 32 occurrences | These involve privileged mount hooks, configured fstab paths or root `nsenter --join-cgroup`. Mount and umount are absent; nsenter remains and fstab is unconfigured. The crawler invokes none of them. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | libacl1 2.3.2-2+b1; 1 occurrence | libacl is present. Exploitation requires a privileged caller processing an attacker-controlled path. Packaged crawler code does not call the affected ACL interfaces. |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | ncurses 6.5+20250216-2; four binary packages, 4 occurrences | The affected infocmp command is present, but the crawler never invokes it or processes terminal descriptions. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | libsystemd0 and libudev1 257.13-1~deb13u1; 2 occurrences | The advisory targets systemd-homed. Its executable is absent from the inspected runtime image; the batch does not run a homed service. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | perl-base 5.40.1-6+deb13u1; 1 occurrence | The advisory targets Archive::Tar; its Tar.pm module is absent. The crawler does not invoke Perl or extract downloaded source archives. |

The documented service uses UID 10001, drops all capabilities, sets
`no-new-privileges`, makes the root filesystem read-only and exposes no network
listener. These controls constrain the privileged paths above; changing them
requires a new applicability review. Source metadata remains untrusted input.

## Reproduce and retain evidence

Use a checksum-verified Trivy 0.74.0 binary. Export the locally built immutable
image and download the public database before scanning:

```sh
docker image save --output image.tar "$RELEASE_IMAGE"
trivy image --download-db-only --db-repository ghcr.io/aquasecurity/trivy-db:2 \
  --cache-dir ./trivy-cache --disable-telemetry --skip-version-check
trivy image --input image.tar --cache-dir ./trivy-cache \
  --offline-scan --skip-db-update --skip-java-db-update --skip-check-update \
  --skip-vex-repo-update --disable-telemetry --skip-version-check \
  --scanners vuln --ignorefile /dev/null --list-all-pkgs --timeout 3m \
  --format json --output image-scan.json --exit-code 1
```

Set `RELEASE_IMAGE` to the immutable image digest being accepted. The scan command
returns 1 when advisories are found; that is separate from scanner failure. The
hardening measurement used the cached database and local Docker socket with
offline scanning, `--ignorefile /dev/null` and the full package inventory; it
performed no image, source or findings upload. A later database can produce
different results. [Trivy documents archive scanning and offline options](https://trivy.dev/docs/v0.74/references/configuration/cli/trivy_image/).

Raw baseline evidence remains in ignored `.poc/current-focus/final-trivy.json`.
The hardening build, apt dependency simulation, full scan, component-presence
evidence and native smoke results are under ignored
`.poc/prod-readiness/security/`; verified scanner downloads and
checksums are under `.poc/tools/trivy/`. These are validation records, separate
from ecosystem opportunity findings.

Before deployment, the security owner must review all residual severities and
record remediation or an explicit, dated acceptance of the exact image and
deployment controls. Repeat scanning before each release and as advisories or
base images change; assign an owner and deadline to unresolved findings. Update
the pinned base/dependencies and repeat native tests after remediation. This
scan does not certify absence of undisclosed flaws, every embedded native
library, or unsafe deployment configuration. Live-model authorization and
operational acceptance remain separate gates in [README.md](README.md).
