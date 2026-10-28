# PoC2 production acceptance

The release target is the private scheduled batch and its internal reports.
The loopback review page is a separate demo tool and is not packaged or exposed
by the batch image. An authenticated report portal is outside this release.

Passing code tests is necessary but does not establish production approval.
Keep the exact commit, immutable image, configuration and dated evidence with
the release decision. The table below names roles; actual owners are not yet
assigned in this repository.

| Decision or check | Evidence required | Owner / current status |
| --- | --- | --- |
| Code and packaging | Native Arm64 tests, image default-command smoke, report consistency and recovery drill on the submitted revision | Engineering: automated checks available |
| Source and opportunity scope | Agreed repository topics, image tags, budgets and a reviewed sample showing useful scoped findings; unknown is not unsupported and zero gaps is valid | Ecosystem product/engineering owner: acceptance pending |
| AI-assisted mode | Approved provider/model, dedicated access and data policy; actual provider run with sufficient fresh findings and complete advisory coverage; human review of every pilot note | Model/service owner and ecosystem reviewer: pending |
| Security | Dated scan of the exact image plus remediation or an explicit dated disposition of residual advisories | Security owner: pending; see SECURITY.md |
| Private host | Storage/permissions, manual run, failure alert, deadline cleanup, backup retrieval/restore and reboot/schedule behavior | Deployment/operations owner: pending |
| Report access and recurring schedule | Approved recipients, private location, retention, quotas, named operator and schedule decision | Service owner: pending; timer remains disabled |

Metadata-only operation is a distinct, explicitly labelled mode. It must not be
presented as the completed AI-assisted requirement. The team may accept it as a
separate initial release; that product decision has not been made here.

## Run evidence verification

The existing batch flags `--fail-on-errors --require-ai` reject configuration,
collection and advisory failures. A healthy no-work batch can still exit zero;
it does not demonstrate acceptance of fresh findings or an actual model call.

From the checkout with the development requirements installed, verify the
saved JSON for the run selected for acceptance:

```sh
python -m poc.discovery.deploy.verify_acceptance \
  /private/acceptance/RUN_ID/opportunities.json \
  --mode ai --minimum-findings 8 --max-age-hours 24
```

This command is read-only and makes no source or model requests. It requires a
nonempty, recent, healthy run; consistent current status counts and observation
dates; and completed, cited advisories for every evidence-bearing current
finding in AI mode. History and retired records do not satisfy the threshold.
The default mode is `ai`; `--mode metadata` explicitly checks metadata-only
evidence. Select the minimum finding count with the team; eight matches the
example collection allowance and is not a demand to find eight support gaps.

The JSON result includes the report SHA-256 and always records
`production_approval: not_established`. Exit 0 means these automated checks
passed, 2 means acceptance checks failed, and 1 means the input was unreadable.
The verifier does not establish live-provider provenance, semantic correctness
of a model note, image security acceptance or host approval. Synthetic fixtures
can test the verifier but cannot prove live AI quality.

For a reviewed eight-finding AI pilot, use a copied acceptance state or fresh
approved scopes, enable the approved provider, and set `ai_review.max_calls`
to at least eight with an approved time/output allowance. The current example
allows only four calls and has AI disabled. A different approved service, such
as an internal model gateway, needs its own validated adapter; generic IDE
credentials or unrelated onboarding permission are not sufficient evidence.

The human reviewer records, for each pilot finding: source identity, checked
artifact scope, whether the status follows the evidence, whether the advisory
adds only supported claims, and whether the proposed next action is useful.
Any invented package, unsupported conclusion or widened project-wide claim
must be corrected before acceptance. Keep coverage questions distinct from
support gaps and include repository and container examples.

## Recovery and host acceptance

Run the [offline recovery drill](README.md#executable-offline-recovery-drill)
before deployment. It verifies actual abrupt-process interruption, a consistent
SQLite backup, checksum-verified restore and continued queued work without
changing original evidence. It does not configure the host backup service.

On the designated private host, record the following against the exact release:

1. Manual batch succeeds with the intended identity, configuration, outbound
   endpoints, persistent local storage and private report permissions.
2. A controlled source failure reaches the real alert destination and operator.
3. The service deadline stops only its own container; subsequent runs retain
   completed observations and report the interrupted run.
4. An approved encrypted backup can be retrieved and restored separately;
   observations, retirement memory and historical reports survive.
5. Reboot and the proposed timer behave as intended, with no duplicate workers;
   disk capacity and retention are reviewed. Enable recurrence only after the
   owner accepts these results.

Do not alter old reports to simulate fresh work or enable a public endpoint to
complete this checklist. Browser interaction is a separate demo acceptance
item: local automation is currently blocked by `ERR_BLOCKED_BY_CLIENT`, while
HTTP and renderer checks pass. This does not test or approve the private host.
