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
| `records` | One record per canonical top-level `.md` package page, sorted by `content_path` |

Each record contains:

| Field | Contract |
|---|---|
| `slug` | Safe package slug matching the Markdown filename; aggregate control-workflow names are reserved |
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
required. During this dormant bootstrap phase, exhaustive pip coverage requires
PyPI evidence and exhaustive npm coverage requires npm-registry evidence.
Unknown or ambiguous dimensions are never exhaustive.

Evidence timestamps use canonical RFC3339 text with an uppercase `T`, seconds,
an optional one-to-six digit fractional second, and either `Z` or a colonized
numeric offset. `generated_workflow` evidence is accepted only when its locator
and SHA-256 exactly match the present workflow already bound by that record.
It cannot cite another workflow or supply an unrelated digest.

Schema `1.1` source kinds use this conservative immutable-revision profile. It
is a strict subset of values accepted by the service consumer and does not
broaden that contract:

| Evidence source | Canonical `source_revision` |
|---|---|
| `generated_workflow` | Exactly 40 lowercase hexadecimal characters identifying the dashboard Git commit |
| `github_api` | Exactly 40 or 64 lowercase hexadecimal characters identifying a Git object |
| `frontmatter_url` | Exactly 64 lowercase hexadecimal characters identifying the source snapshot SHA-256 |
| `pypi_api` | Exactly 64 lowercase hexadecimal characters identifying the API snapshot SHA-256 |
| `npm_api` | Exactly 64 lowercase hexadecimal characters identifying the API snapshot SHA-256 |

`manual_review` remains a reserved schema value, but this dormant bootstrap
validator rejects every occurrence. It cannot authenticate a reviewer or an
approval from catalog text alone. A separately reviewed change may enable it
only after an authenticated external approval verifier, path-specific
CODEOWNERS, required reviews, and repository rulesets are operating.

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

The complete corpus is also bounded to 10,000 package pages and 20,000 directory
entries. Only the exact root `_index.md` is exempt. Nested directories and every
other extension or file type fail closed. The complete immutable commit snapshot
is limited to 512 MiB, 30,050 regular-file entries, and 20 MiB per auxiliary file.

## Immutable Revision Boundary

The production command never validates mutable working-tree bytes. It accepts
only `HEAD` or an exact full lowercase Git commit ID, disables Git replace
objects, enumerates the complete commit tree with `git ls-tree`, and reads each
exact regular-file blob with `git cat-file`. Object type, mode, ID, recomputed Git
blob hash, path, count, individual size, and aggregate bytes are checked before
the payloads are written into a private temporary snapshot. Git archive export
rules and mutable worktree bytes are therefore outside the evidence path.

The validator also creates an isolated bare Git repository backed only by the
reviewed object database, checks out the exact commit with a fresh index and no
user or system Git configuration, and recomputes every checked-out file's Git
blob ID. Any `ident`, end-of-line, text, or working-tree-encoding transformation
that changes deployed bytes fails. Named checkout filters are rejected because
their behavior depends on configuration outside the reviewed commit.

The descriptor-bound validator below then evaluates only that snapshot. Dirty
files, untracked files, branch movement after resolution, and concurrent
working-tree edits cannot change the evidence under review. The private
snapshot is deleted after every run.

## Exact Hugo Boundary

The catalog covers the effective production Hugo graph, not only one physical
directory. The validator requires a checksum-pinned Hugo `0.130.0` binary and:

- inspects Hugo's own `config mounts` output and permits only the current project
  and `arm-design-system-hugo-theme` mounts;
- blocks remote module configuration, alternate config directories, vendored
  modules, case-insensitive `themesDir` or security overrides in either production
  config, repository-controlled cache/build-output paths, theme config overrides,
  and `_content*.gotmpl` adapters before page evaluation;
- parses bounded `hugo list all` CSV and requires exactly one canonical effective
  page and URL for every cataloged package source;
- rejects any mounted, theme, or external page that claims a protected package
  URL, any alias, and any project or theme static file below the protected package
  route;
- performs a marker render with an entirely validator-owned theme and layout graph,
  plus an appended deny-by-default Hugo security policy for HTTP, process execution,
  environment access, and inline shortcodes. Repository and reviewed-theme
  templates never execute in this source-ownership probe;
- writes a source marker into every regular rendered page, binds each marker back
  to the exact `hugo list all` source/route pair, and requires the marker-rendered
  protected routes to exactly match the catalog; and
- performs a second render with the real production project layouts and reviewed
  theme under the same deny-by-default policy. Its complete protected-route
  inventory must remain empty because the current dashboard does not publish
  individual package-detail pages. Any future detail-page rollout therefore needs
  an explicit contract update, and template-generated resources cannot silently
  publish files below a package route.

Both render workspaces monitor file count, total bytes, per-file bytes, path depth,
and runtime while Hugo executes, with an OS file-size limit applied to the child.
Every bounded command runs in a private process group that is terminated and reaped
on success, failure, or timeout, including any descendant processes. Build locks are
disabled for every Hugo subcommand, and the source snapshot must remain byte-for-byte
and path-for-path unchanged across topology validation.

Hugo receives an allowlisted environment with module downloads disabled and no
repository or organization credentials.

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

Run the read-only validator from the repository root with the checksum-verified
Hugo binary used by production:

```bash
python3 -I -B build_steps/validate_package_identity_catalog.py \
  --revision HEAD \
  --hugo-binary /trusted/tools/hugo-0.130.0/hugo
```

The CLI fails closed unless Python isolated mode (`-I`) is active. The guard
runs before imports that repository-controlled Python files could shadow. `-B`
also prevents the validation command from writing bytecode into the reviewed
checkout.

For a caller that already possesses the reviewed commit identity, replace
`HEAD` with that exact 40-character commit ID. Branch names, tags, abbreviated
IDs, and other moving revision expressions are rejected.

The command exits nonzero when the catalog is missing or malformed, package
coverage is incomplete, a page or workflow hash is stale, declared workflow
presence is wrong, identities are non-normalized, or the same pip/npm identity
is claimed by multiple pages. It also rejects package workflows without an
exact package page. Numbered batch workflows, the package orchestrator, and the
package summary workflow are explicitly treated as control workflows rather
than package identities.

Focused tests use isolated temporary repositories and do not read or modify the
dashboard package corpus. Set `PACKAGE_CATALOG_HUGO_BINARY` to the trusted exact
binary:

```bash
PACKAGE_CATALOG_HUGO_BINARY=/trusted/tools/hugo-0.130.0/hugo \
  python3 -I -B tests/test_package_identity_catalog.py -v
```

The tests cover ancestor and final-component symlinks, pathname replacement
during and after descriptor reads, FIFO/socket/device candidates, injected
descriptor failures and leak checks, hard links, bounded page/workflow reads,
stale hashes, catalog coverage, duplicate identities, immutable evidence
revisions, dirty-worktree isolation, bounded exact-object materialization,
committed and local Git attribute bypasses, clean-checkout byte transformations,
external filters, Hugo mounts, theme content, content adapters, URL and alias route
claims (including aliases aimed at existing routes), project/theme static route
collisions, case-insensitive config bypasses, marker-render template isolation,
production-template resource publication, direct HTTP denial, rendered-output
amplification, external type-specific cache writes, build-stat output, descendant
process cleanup, selector cleanup, noncanonical Hugo content paths, control
workflow names, source-snapshot non-mutation, canonical timestamps, and
generated-workflow evidence binding. A real subprocess regression also places a
hostile `build_steps/hashlib.py` beside the validator: nonisolated invocation
must fail, while the isolated invocation must complete validation. Manual-review
evidence is rejected until external authentication and repository governance
exist.

The bootstrap-only
`.github/workflows/package-identity-bootstrap-unit-tests.yml` workflow downloads
the exact Arm64 Hugo release, verifies its pinned SHA-256 before extraction, and
runs the isolated trust-boundary suite. It intentionally does not run the live
validator while the reviewed catalog is absent, and it is not the future required
trust-root check described below.

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
2. Inventory every canonical top-level `.md` file below
   `content/linux/opensource_packages`. Only the exact root `_index.md` is exempt;
   nested directories and alternate Hugo-renderable extensions fail closed.
3. Bind each page and canonical `.github/workflows/test-<slug>.yml` as present
   or absent with exact SHA-256 values.
4. Review pip and npm independently for every page.
5. Record immutable evidence metadata for every dimension. A generated
   worksheet may use honest `frontmatter_url` or `generated_workflow` evidence
   where valid, with unknown and non-exhaustive decisions left for review.
6. Mark coverage exhaustive only when registry evidence demonstrates that all
   identities for that dimension were considered.
7. Run the exact checkout, Hugo topology, rendered-route, and catalog validator
   gates against the proposed merge tree.
8. Add the validator as a required pull-request check before the catalog can
   authorize any no-match decision.
9. Configure path-specific CODEOWNERS, required human review, and repository
   rulesets before any authenticated manual-review verifier can be enabled.

`manual_review` is reserved for a future authenticated approval verifier and is
rejected by this dormant validator. Bootstrap automation must never emit that
source kind or fabricate a human attestation. It must also never infer
`not_applicable` or exhaustive coverage from a missing workflow, a missing URL,
an unapproved URL, frontmatter, or generated shell commands.

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
