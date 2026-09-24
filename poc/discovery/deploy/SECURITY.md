# Image security validation — 24 September 2026

The implementation is ready for code review. **Production security acceptance
remains open:** the final image retains eight distinct HIGH advisory IDs that
need an operational security owner's disposition or further remediation. No
findings were suppressed and no risk waiver was granted.

## Exact image and scan

- Final Linux Arm64 image index:
  `sha256:40a71b70f8610bb2f32f002172d8ef93f7eddc6c2d10668e6cc4881c069da5b8`.
- Image configuration digest, as reported by Trivy:
  `sha256:f5d3a246b08538c52c105cb9b1687b2ab04cf46ed0c7da037f42de14f8099a92`.
- Scanner: [Trivy 0.74.0 official immutable release](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0).
  The downloaded macOS Arm64 archive matched both its official checksum file
  and GitHub release asset digest:
  `1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11`.
- Database: `ghcr.io/aquasecurity/trivy-db:2`, updated
  `2026-09-24T13:23:01Z`; scan completed `2026-09-24T17:57:02Z`.

The local Docker archive links the image index to the configuration digest.
Scanning inspected 87 Debian 13.7 packages and nine Python packages. These are
**package/advisory occurrences**, so one advisory can appear against several
binary packages built from the same source package.

| Final result | Critical | High | Medium | Low | Unknown | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Debian packages | 0 | 44 | 53 | 57 | 2 | 156 |
| Python packages | 0 | 0 | 0 | 0 | 0 | 0 |

There are 68 distinct advisory IDs overall; eight account for the 44 HIGH
occurrences. The database supplies no fixed Trixie version for these remaining
findings. Some severity ratings come from other vendors; package matching is
not proof of exploitability in this application.

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

## Remaining HIGH advisory applicability

All rows below have **no fixed Trixie package version listed** on the scan date.
The observations describe the inspected image and intended batch deployment;
they do not approve an exception to security policy.

| Advisory IDs | Installed packages / occurrences | Observed boundary |
| --- | --- | --- |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | util-linux source package 2.41.5-0+deb13u1; nine binary packages, 36 occurrences | These involve privileged mount hooks, configured fstab paths or root `nsenter --join-cgroup`. Mount and nsenter are present; fstab is unconfigured. The crawler invokes neither. |
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
docker image save --output image.tar sha256:40a71b70f8610bb2f32f002172d8ef93f7eddc6c2d10668e6cc4881c069da5b8
trivy image --download-db-only --db-repository ghcr.io/aquasecurity/trivy-db:2 \
  --cache-dir ./trivy-cache --disable-telemetry --skip-version-check
trivy image --input image.tar --cache-dir ./trivy-cache \
  --offline-scan --skip-db-update --skip-java-db-update --skip-check-update \
  --skip-vex-repo-update --disable-telemetry --skip-version-check \
  --scanners vuln --ignorefile /dev/null --list-all-pkgs --timeout 3m \
  --format json --output image-scan.json --exit-code 1
```

The final command returned 1 because advisories were found, not because scanning
failed. The actual scan used an isolated environment, disabled telemetry and
performed no image, source or findings upload. A later database can produce
different results. [Trivy documents archive scanning and offline options](https://trivy.dev/docs/v0.74/references/configuration/cli/trivy_image/).

Raw reports, every finding with installed/fixed versions, database metadata and
component-presence evidence stay in ignored local
`.poc/validation/production-final-image-*` files; verified scanner downloads and
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
