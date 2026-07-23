# Package Identity Catalog

## Purpose

The dashboard package identity catalog is a reviewed trust root for package
identity decisions. It binds every Linux package page and its expected package
workflow to exact bytes, while recording pip and npm identity decisions
separately.

The catalog must not infer package identity from install commands, arbitrary
workflow text, or an AI response. A digest proves that reviewed bytes have not
changed; it does not prove that a registry identity or an exhaustive-coverage
decision is true.

The production catalog path is:

```text
.github/package-identity-catalog.json
```

That file is intentionally not bootstrapped by this safeguard slice. The
repository does not currently contain reviewed pip/npm decisions, evidence
reviewers, or exhaustive-coverage determinations for the complete package
corpus. Generating positive or `not_applicable` decisions from existing shell
commands would create an unsupported trust claim.

## Audited Baseline

At dashboard commit
`a3cdc05f04278a65ad1e89adf1895d004f31eaac` (`origin/main` when audited), the
repository contains:

- 983 non-index package pages
- 960 exact `.github/workflows/test-<slug>.yml` package workflows
- 23 package pages with no package workflow
- no orphan package workflow
- no case-insensitive package filename collision
- no package identity catalog or CODEOWNERS file

These counts are corpus inventory, not package-identity evidence. The 23 absent
workflows include pages whose download URLs are missing or outside the approved
evidence hosts. A catalog bootstrap must therefore represent unresolved
registry dimensions as unknown and non-exhaustive unless independently
verified; the inventory alone cannot produce a fully approved final catalog.

## Deterministic Format

The validator implements schema version `1.1`, matching the package-onboarding
service contract. JSON is canonical:

- UTF-8 with ASCII escaping
- object keys sorted lexicographically
- two-space indentation
- exactly one trailing newline
- no duplicate object keys or unrecognized fields

The top-level object contains:

| Field | Contract |
|---|---|
| `schema_version` | Exactly `"1.1"` |
| `corpus` | Content root, record count, and canonical corpus SHA-256 |
| `records` | One record per non-index Markdown page, sorted by `content_path` |

Each record contains:

| Field | Contract |
|---|---|
| `slug` | Safe package slug matching the Markdown filename |
| `content_path` | Repository-relative package page path |
| `content_sha256` | SHA-256 of the exact page bytes |
| `workflow` | Canonical workflow path, `present`/`absent`, and exact SHA-256 or `null` |
| `registries` | Independent `pip` and `npm` identity dimensions |

Each registry dimension contains:

| Field | Contract |
|---|---|
| `status` | `verified`, `not_applicable`, `unknown`, or `ambiguous` |
| `exhaustive` | Whether reviewed evidence covers the complete registry dimension |
| `identities` | Sorted, unique, registry-normalized identifiers |
| `evidence` | Canonically sorted reviewable evidence records |

Evidence records identify the source kind, locator, immutable source revision,
evidence SHA-256, reviewer, timezone-aware review time, and rationale where
required. Exhaustive pip coverage requires PyPI or manual-review evidence;
exhaustive npm coverage requires npm-registry or manual-review evidence.
Unknown or ambiguous dimensions are never exhaustive.

Schema `1.1` source kinds use this conservative immutable-revision profile. It
is a strict subset of values accepted by the service consumer and does not
broaden that contract:

| Evidence source | Canonical `source_revision` |
|---|---|
| `generated_workflow` | Exactly 40 lowercase hexadecimal characters identifying the dashboard Git commit |
| `github_api` | Exactly 40 or 64 lowercase hexadecimal characters identifying a Git object |
| `manual_review` | Exactly 40 or 64 lowercase hexadecimal characters identifying reviewed Git or content state |
| `frontmatter_url` | Exactly 64 lowercase hexadecimal characters identifying the source snapshot SHA-256 |
| `pypi_api` | Exactly 64 lowercase hexadecimal characters identifying the API snapshot SHA-256 |
| `npm_api` | Exactly 64 lowercase hexadecimal characters identifying the API snapshot SHA-256 |

Floating names and aliases such as `latest`, `main`, `master`, `HEAD`,
`refs/heads/main`, tags, and bare version labels are not immutable revisions and
are rejected. All-zero 40- and 64-character revisions are also rejected because
they do not identify a real Git object or content snapshot.

The corpus digest is calculated over every package page and expected workflow:

```text
repository/path<NUL>sha256:lowercase_sha256<LF>
repository/path<NUL>absent<LF>
```

Entries are sorted by repository path before hashing. This binds both exact
bytes and reviewed workflow absence.

Reads use the same inclusive limits as the service consumer and reject empty
files:

| File role | Accepted byte size |
|---|---|
| Catalog JSON | 1 through 20,000,000 |
| Package page | 1 through 2,000,000 |
| Package workflow | 1 through 2,000,000 |

Repository reads are descriptor-bound:

- The repository root itself must be a real directory, not a symbolic link.
- Each descendant directory is opened relative to its trusted parent directory
  descriptor with `O_DIRECTORY`, `O_NOFOLLOW`, and `O_CLOEXEC`.
- Catalog, package-page, and workflow files are opened relative to the trusted
  parent descriptor with `O_NONBLOCK`, `O_NOFOLLOW`, and `O_CLOEXEC`.
- `fstat` must identify a regular file within its role-specific size bound
  before any bytes are read.
- Every protected catalog, package-page, and workflow file must have
  `st_nlink == 1`. Hard-linked protected files fail closed so another pathname
  cannot mutate the reviewed inode.
- Bounded `os.read` calls may consume at most one byte beyond the limit, which
  is used only to reject concurrent growth.
- Descriptor state and the parent directory entry identity are rechecked after
  reading. In-place mutation and pathname replacement both fail closed.
- Package and workflow directory inventories are checked for changes during
  traversal.
- After all semantic checks, the validator securely re-walks the protected tree
  and compares device, inode, mode, link count, size, `mtime_ns`, `ctime_ns`,
  and directory names against the first trusted snapshot. This final gate
  covers the catalog, every package page, every workflow YAML file, the
  repository root, and each traversed protected directory.
- Descriptor cleanup is unconditional when `open`, `fstat`, traversal, or read
  checks fail.

Platforms without the required descriptor-relative APIs or open flags fail
closed. Linux CI provides the required interface.

## Validation

Run the read-only validator from the repository root:

```bash
python3 build_steps/validate_package_identity_catalog.py
```

The command exits nonzero when the catalog is missing or malformed, package
coverage is incomplete, a page or workflow hash is stale, declared workflow
presence is wrong, identities are non-normalized, or the same pip/npm identity
is claimed by multiple pages. It also rejects package workflows without an
exact package page. Numbered batch workflows, the package orchestrator, and the
package summary workflow are explicitly treated as control workflows rather
than package identities.

Focused tests use isolated temporary repositories and do not read or modify the
dashboard package corpus:

```bash
python3 -m unittest -v tests.test_package_identity_catalog
```

The tests cover ancestor and final-component symlinks, pathname replacement
during and after descriptor reads, FIFO/socket/device candidates, injected
descriptor failures and leak checks, hard links, bounded page/workflow reads,
stale hashes, catalog coverage, duplicate identities, and immutable evidence
revisions.

The bootstrap-only
`.github/workflows/package-identity-bootstrap-unit-tests.yml` workflow runs
that isolated standard-library unit-test command. It intentionally does not run
the live validator while the reviewed catalog is absent, and it is not the
future required trust-root check described below.

The safeguard slice contains:

| Path | Purpose |
|---|---|
| `.github/PACKAGE_IDENTITY_CATALOG.md` | Contract and bootstrap trust boundary |
| `.github/workflows/package-identity-bootstrap-unit-tests.yml` | Isolated bootstrap unit-test CI |
| `build_steps/validate_package_identity_catalog.py` | Read-only fail-closed validator |
| `tests/test_package_identity_catalog.py` | Synthetic validator unit tests |

## Bootstrap Requirements

A separately reviewed bootstrap change must:

1. Select and record one exact dashboard base commit.
2. Inventory every non-index file below
   `content/linux/opensource_packages`.
3. Bind each page and canonical `.github/workflows/test-<slug>.yml` as present
   or absent with exact SHA-256 values.
4. Review pip and npm independently for every page.
5. Record immutable evidence metadata for every dimension. A generated
   worksheet may use honest `frontmatter_url` or `generated_workflow` evidence
   where valid, with unknown and non-exhaustive decisions left for review.
6. Mark coverage exhaustive only when registry or manual evidence demonstrates
   that all identities for that dimension were considered.
7. Run the validator against the proposed merge tree.
8. Add the validator as a required pull-request check before the catalog can
   authorize any no-match decision.

`manual_review` is reserved for a real review by the named human in
`verified_by`. Bootstrap automation must never emit that source kind or
fabricate a human attestation. It must also never infer `not_applicable` or
exhaustive coverage from a missing workflow, a missing URL, an unapproved URL,
frontmatter, or generated shell commands.

Until that bootstrap and required check are independently reviewed, a missing
catalog must remain a fail-closed condition.

## Unresolved Ownership Mapping

No `.github/CODEOWNERS`, `OWNERS`, or `MAINTAINERS` file currently identifies an
accountable catalog steward or workflow-security owner. The existing test
documentation refers only to generic maintainer roles, and commit frequency is
not ownership evidence. Therefore this change does not invent GitHub users or
teams and does not add CODEOWNERS entries.

The repository teams endpoint was empty when audited. Direct repository access
showed `zachlasiuk` (admin), `chrismoroney` (maintain), and `ranimandepudi`
(admin), but permission level does not establish responsibility for this
catalog. Those accounts are therefore not used as inferred CODEOWNERS.

The following exact path mapping remains unresolved:

| Protected path | Required accountable role | GitHub owner |
|---|---|---|
| `.github/package-identity-catalog.json` | Dashboard identity-catalog steward | Unresolved |
| `.github/workflows/package-identity-bootstrap-unit-tests.yml` | Workflow-security reviewer | Unresolved |
| `build_steps/validate_package_identity_catalog.py` | Identity-catalog steward and workflow-security reviewer | Unresolved |
| `tests/test_package_identity_catalog.py` | Identity-catalog validator maintainer | Unresolved |
| `.github/PACKAGE_IDENTITY_CATALOG.md` | Identity-catalog steward | Unresolved |

An authorized repository owner must provide the exact GitHub team or user for
each role before path-specific CODEOWNERS protection is added. The catalog
bootstrap must not proceed on the assumption that a frequent contributor is
the owner.
