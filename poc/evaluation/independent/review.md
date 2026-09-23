# Independent final review — conversational search local PoC

**Verdict: ready for bounded local PoC review, with the recall limits below explicitly disclosed.** No previously confirmed P1/P2 precision or evidence-attribution blocker remains in the established checks. This verdict does **not** establish broad natural-language feature acceptance or production readiness.

The final implementation resolves the reviewed false-result classes and prefers an explained no-match when it cannot verify a requirement. That conservative choice leaves eight ordinary, catalog-supported requests without their expected packages. Those misses remain visible in the evidence; the assertions were not weakened to label them successful.

The exact reviewed Python source hashes and generated-catalog hash are recorded in [manifest.json](manifest.json). Source remained frozen during the final checks. This reviewer edited only ignored review artifacts; no tracked source, PR comment, commit, or push was made by this reviewer.

## Final evidence

| Check | Observed result |
| --- | --- |
| Disclosed, strengthened HTTP scenarios | 36 of 38 met all assertions; two returned no expected package |
| Eight additional examples, originally held back until candidate 2 | Two met all assertions; six returned no expected package |
| Targeted precision and evidence confirmations | All 10 passed |
| Independent final Python suite | 122 passed |
| Catalog identity verification across the 46 HTTP requests | All 108 returned rows, representing 63 distinct IDs, matched catalog fields and real content files |
| HTTP status and latency | All 46 returned HTTP 200; largest observed response time was 7.56 seconds |
| Provider fallback | Two disclosed cases used clearly labeled catalog fallback; all eight additional examples used live hybrid retrieval |

These are finite scenario counts, not an accuracy percentage. Required-name presence alone was insufficient during earlier candidates, so the final cases also check known false positives, evidence attribution, filter inheritance, and real record identity. Returned rows were manually inspected for the established role and qualifier failures.

The full final responses are in [regression-http.json](regression-http.json) and [fresh-http.json](fresh-http.json). The expectations are in [regression_cases.json](regression_cases.json) and [fresh_cases.json](fresh_cases.json). Both sets are now disclosed regression and recall probes; neither should be represented as an unseen final benchmark. [README.md](README.md) describes rerunning them.

## Confirmed corrections

- Question/first-person wording works for the reviewed supported vector, relational, queue, monitoring, compression, and local-model requests. Postgres appears in relational/SQL results; Sqoop is excluded as a database and appears when the request actually asks for data transfer.
- KB evidence can establish a real workload match: a controlled RabbitMQ passage adds a relevant result absent from catalog-only matching. Generic article words such as Vector, Agent, and Benchmark no longer establish the wrong product's identity in the reviewed cases.
- Incidental deployment passages no longer make Terraform a load balancer or MySQL/WordPress web servers. Catalog identity and software role checks remain in place.
- Reviewed subtype, protocol, disk, and live-backup requirements are preserved. MQTT requests exclude unrelated brokers; live MySQL backups return Xtrabackup without Percona; packet-capture requests return Libpcap without DPDK.
- Negated attributes are rejected in grouped and ungrouped queries. Identical open-source/commercial display names do not inherit the other edition's KB-only feature claim.
- URL schemes no longer supply HTTPS capability evidence. Replaying the captured NGINX deployment passage does not establish automatic HTTPS; Caddy remains a valid match.
- Filter-only follow-ups preserve the previous software subject; a new web-server subject replaces vector intent. Existing category, license, test-record, and edition checks pass. Unsupported exclusions and compositions receive notices instead of silently broadening the request.

[Targeted confirmations](targeted-confirmations.json) distinguish synthetic transport fixtures from live-provider observations. The automatic-HTTPS confirmation replays a captured real passage; its source metadata and digest are retained without reproducing the full external article passage.

## Remaining recall limits

Every query below returned no packages with an explanatory notice in the final run, despite a relevant record in the catalog:

| Case | Query | Expected catalog record |
| --- | --- | --- |
| h10 | I am trying to find a toolkit for TLS connections. | OpenSSL |
| h12 | Please help us automate configuration management with playbooks. | Ansible |
| f01 | I would like a database built around nodes and relationships. | Neo4j / Neo4j Graph Database |
| f02 | Is there a web server that deals with HTTPS automatically? | Caddy |
| f03 | Which open-source databases are meant for time-stamped measurements? | TimescaleDB |
| f04 | Could I get a tool to convert scans into text? | Tesseract |
| f07 | Read and write geospatial data formats | Geospatial Data Abstraction Library (GDAL) |
| f08 | Programs to make ZIP archives | 7-zip |

These are actual limitations of the PoC's natural-language coverage. Strict positive concept matching prevents unsupported matches but retains some conversational wording as required concepts and has limited inflection handling. For example, the current matcher treats `write` and `writing` differently. The OpenSSL, Ansible, and GDAL requests matched earlier, looser candidates but no longer pass the stricter evidence requirements. This tradeoff is disclosed rather than hidden by changing the expected result.

Direct live-KB inspection helps distinguish provider recall from local admission. In the recorded 50-hit responses for the additional examples, the expected Neo4j, Caddy, Tesseract, and 7-zip names were absent from all titles, headings, and snippets. TimescaleDB appeared only at position 50, in a database-extension setup passage. The catalog supplies its timestamped-data capability. GDAL did have a directly mapped relevant KB hit, so its final miss demonstrates a local matching limitation. The data-transfer example originally lacked a Sqoop KB hit but now succeeds through the catalog.

[Provider recall observations](provider-recall-observations.json) retain the exact interpreted queries, hit counts, expected-name checks, and relevant source URLs. Those observations were collected after candidate 2; live provider ranking can change. No claim is made that an LLM is necessary or that the provider alone can satisfy the feature.

## Local service boundary

The KB client's bounded admission, completion callbacks, response-size handling, and exception cleanup were independently reviewed, and its 10 offline tests passed as part of the suite. A caller timeout retains the running worker's slot until completion, preventing an unbounded retry queue. The eight-second limit bounds caller waiting; it is not cancellation of a running network operation or a hard shutdown deadline.

Earlier independent actual-HTTP checks verified labeled provider outage behavior and validation/origin/body-size boundaries. Root's browser, build, upstream-suite, and slow-provider HTTP results are recorded separately in the PoC results document.

The resolved precision defects make this a useful local artifact for stakeholder review. Broader natural-language acceptance still requires an agreed relevance corpus and more query-coverage work. The eight remaining misses should accompany any demonstration or review summary.
