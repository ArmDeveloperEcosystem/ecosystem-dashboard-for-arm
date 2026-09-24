"""Process-local verified results with live, transitive evidence dependencies.

Only reviewed callers populate this cache, after their full verifier returns.
Nothing is serialized. Completed attempt jobs and digest-checked artifact bytes
need not be downloaded again, but latest runs, inventories, refs and artifact
metadata are refreshed before a top-level verification returns to its caller.
Repeated JSON reads inside that read-only boundary share one snapshot; the final
refresh bypasses it. A quota wait restarts the mutable refresh from the beginning.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time

from orchestration_contract import ContractError

MAX_ENTRIES = 128
MAX_DEPENDENCIES = 2048
MAX_VALUE_BYTES = 16 * 1024 * 1024
MAX_READ_BYTES = 64 * 1024 * 1024
_RUN = re.compile(r"(repos/[^/]+/[^/]+/actions/runs/[1-9][0-9]*)(?:/attempts/([1-9][0-9]*))?$")
_JOBS = re.compile(r"(repos/[^/]+/[^/]+/actions/runs/[1-9][0-9]*)/attempts/([1-9][0-9]*)/jobs(?:\?.*)?$")
_ARTIFACT = re.compile(r"repos/[^/]+/[^/]+/actions/artifacts/([1-9][0-9]*)/zip$")


def _json(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(raw.encode()) > MAX_VALUE_BYTES:
            raise ValueError()
        return raw
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContractError("verification cache value is not bounded JSON") from exc


def _run(value):
    # Repository API objects include unrelated, mutable repository statistics.
    keys = ("id", "run_attempt", "head_sha", "head_branch", "path", "event",
            "workflow_id", "run_number", "created_at", "run_started_at",
            "display_title", "name", "url", "html_url")
    result = {key: value[key] for key in keys if key in value}
    for key in ("repository", "head_repository"):
        if key in value:
            item = value[key]
            result[key] = {k: item[k] for k in ("id", "full_name", "private") if k in item} if type(item) is dict else item
    if "head_commit" in value:
        item = value["head_commit"]
        result["head_commit"] = {"id": item.get("id")} if type(item) is dict else item
    if value.get("status") == "completed":
        result.update({key: value.get(key) for key in ("status", "conclusion", "updated_at")})
    return result


def _projection(endpoint, value):
    if _RUN.fullmatch(endpoint) and type(value) is dict:
        return _run(value)
    if type(value) is dict and "workflow_runs" in value:
        rows = value["workflow_runs"]
        if type(rows) is list and all(type(row) is dict for row in rows):
            return {"total_count": value.get("total_count"), "workflow_runs": [_run(row) for row in rows]}
    if re.fullmatch(r"repos/[^/]+/[^/]+", endpoint) and type(value) is dict:
        return {key: value.get(key) for key in ("id", "full_name", "private")}
    return value


@dataclass
class _Evidence:
    dependencies: dict = field(default_factory=dict)
    run_ages: dict = field(default_factory=dict)
    archives: set = field(default_factory=set)
    not_before: float = 0
    not_after: float = float("inf")
    result: object = None


class _Reader:
    def __init__(self, session, api):
        self.session, self.delegate = session, api

    def api(self, endpoint, **options):
        if options.get("payload") is not None:
            raise ContractError("verification sessions cannot authorize API writes")
        key = (endpoint, options.get("pages", False))
        reusable = self.session._frames and not options.get("raw") and endpoint != "rate_limit"
        if reusable and key in self.session._reads:
            value = json.loads(self.session._reads[key])
            self.session._observe(endpoint, options, value)
            return value
        value = self.delegate.api(endpoint, **options)
        if reusable and key not in self.session._reads:
            raw = _json(value)
            self.session._read_bytes += len(raw.encode())
            if self.session._read_bytes > MAX_READ_BYTES:
                raise ContractError("verification read snapshot exceeds byte budget")
            self.session._reads[key] = raw
        self.session._observe(endpoint, options, value)
        return value


def session_for(api=None, session=None):
    if session is not None:
        if type(session) is not VerificationSession:
            raise ContractError("verification requires a real process-local session")
        return session
    inherited = getattr(api, "session", None)
    return inherited if type(inherited) is VerificationSession else None


class VerificationSession:
    def __init__(self, *, wall_clock=time.time):
        self.wall_clock = wall_clock
        self._entries = {}
        self._active = set()
        self._frames = []
        self._wait_generation = 0
        self._reads = {}
        self._read_bytes = 0

    def after_wait(self):
        """A quota sleep cannot leave earlier mutable reads authorizing a write."""
        self._wait_generation += 1

    def reader(self, api):
        return api if type(api) is _Reader and api.session is self else _Reader(self, api)

    def _merge(self, evidence):
        for frame in self._frames:
            for key, expected in evidence.dependencies.items():
                previous = frame.dependencies.get(key)
                if previous is not None and previous != expected:
                    raise ContractError("verification evidence changed within one boundary")
                frame.dependencies[key] = expected
            frame.run_ages.update(evidence.run_ages)
            frame.archives.update(evidence.archives)
            frame.not_before = max(frame.not_before, evidence.not_before)
            frame.not_after = min(frame.not_after, evidence.not_after)
            if len(frame.dependencies) > MAX_DEPENDENCIES:
                raise ContractError("verification dependency budget exhausted")

    def _observe(self, endpoint, options, value):
        if not self._frames or endpoint == "rate_limit":
            return
        if options.get("raw"):
            match = _ARTIFACT.fullmatch(endpoint)
            if match:
                self._merge(_Evidence(archives={int(match[1])}))
            elif not re.fullmatch(r"repos/[^/]+/[^/]+/actions/jobs/[1-9][0-9]*/logs", endpoint):
                raise ContractError("unsupported raw verification dependency")
            return
        key = (endpoint, options.get("pages", False))
        expected = _json(_projection(endpoint, value))
        self._merge(_Evidence(dependencies={key: expected}))

    def _dependencies(self, evidence, api):
        dependencies = dict(evidence.dependencies)
        # Attempt endpoints cannot detect a subsequent rerun. Guard the latest
        # run even when a publisher helper only requested /attempts/1.
        for (endpoint, pages), raw in list(dependencies.items()):
            match = _RUN.fullmatch(endpoint)
            if match and match[2]:
                latest = (match[1], False)
                observed = _projection(match[1], api.api(match[1]))
                expected = json.loads(raw)
                if type(observed) is not dict or _json({k: observed.get(k) for k in expected}) != raw:
                    raise ContractError("publisher attempt is no longer latest")
                if latest in dependencies:
                    prior = json.loads(dependencies[latest])
                    if _json({k: observed.get(k) for k in prior}) != dependencies[latest]:
                        raise ContractError("latest publisher evidence changed")
                dependencies[latest] = _json(observed)
                del dependencies[(endpoint, pages)]
        for key in list(dependencies):
            match = _JOBS.fullmatch(key[0])
            if match:
                latest = json.loads(dependencies.get((match[1], False), "{}"))
                if latest.get("status") == "completed" and latest.get("run_attempt") == int(match[2]):
                    del dependencies[key]
            elif re.fullmatch(r"repos/[^/]+/[^/]+/actions/jobs/[1-9][0-9]*", key[0]):
                job = json.loads(dependencies[key])
                prefix = key[0].split("/actions/jobs/")[0]
                latest = json.loads(dependencies.get((f"{prefix}/actions/runs/{job.get('run_id')}", False), "{}"))
                if latest.get("status") == "completed" and latest.get("run_attempt") == job.get("run_attempt"):
                    del dependencies[key]
        artifacts = set()
        for (endpoint, _), raw in dependencies.items():
            if "/artifacts" not in endpoint:
                continue
            value = json.loads(raw)
            pages = value if type(value) is list else [value]
            for page in pages:
                if type(page) is dict:
                    for artifact in page.get("artifacts", [page]):
                        if (type(artifact) is dict and artifact.get("expired") is False
                                and type(artifact.get("digest")) is str
                                and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])):
                            artifacts.add(artifact.get("id"))
        if not evidence.archives <= artifacts:
            raise ContractError("cached archive has no live artifact integrity dependency")
        return dependencies

    def _refresh(self, evidence, api, now):
        started = self.wall_clock()
        for _ in range(3):
            generation = self._wait_generation
            if self._refresh_once(evidence, api, now, generation, started):
                return
        raise ContractError("mutable evidence cannot be refreshed within the quota window")

    def _refresh_once(self, evidence, api, now, generation, started):
        now += max(0, self.wall_clock() - started)
        if not evidence.not_before <= now <= evidence.not_after:
            raise ContractError("cached verification window expired")
        for (endpoint, pages), raw in evidence.dependencies.items():
            options = {"pages": True} if pages else {}
            observed = _projection(endpoint, api.api(endpoint, **options))
            expected = json.loads(raw)
            # A currently executing publisher can complete, but may not rerun
            # or change any of the identity fields originally authenticated.
            if _RUN.fullmatch(endpoint) and "status" not in expected and type(observed) is dict:
                observed = {key: observed.get(key) for key in expected}
            if _json(observed) != raw:
                raise ContractError("mutable verification evidence changed")
            if generation != self._wait_generation:
                return False
        now = max(now, self.wall_clock())
        if not evidence.not_before <= now <= evidence.not_after:
            raise ContractError("cached verification window expired")
        for endpoint, age in evidence.run_ages.items():
            run = json.loads(evidence.dependencies.get((endpoint, False), "{}"))
            try:
                created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).timestamp()
            except (KeyError, TypeError, ValueError) as exc:
                raise ContractError("cached evidence lacks a freshness binding") from exc
            if not 0 <= now - created <= age:
                raise ContractError("cached verification evidence expired")
        return True

    def verify(self, namespace, identity, api, build, *, root, now=None, run_ages=None, window=None):
        key = (namespace, str(Path(root).resolve()), hashlib.sha256(_json(identity).encode()).hexdigest())
        outer = not self._frames
        if outer:
            self._reads = {}
            self._read_bytes = 0
        if key in self._active:
            raise ContractError("recursive verification dependency")
        try:
            if key in self._entries:
                evidence = self._entries[key]
                if outer:
                    self._refresh(evidence, api, self.wall_clock() if now is None else now)
                self._merge(evidence)
                return deepcopy(evidence.result)
            if len(self._entries) + len(self._active) >= MAX_ENTRIES:
                raise ContractError("verification cache budget exhausted")
            self._active.add(key)
            evidence = _Evidence(run_ages=dict(run_ages or {}))
            if window is not None:
                evidence.not_before, evidence.not_after = window
            self._frames.append(evidence)
            try:
                result = build(self.reader(api))
                _json(result)
            finally:
                self._frames.pop()
                self._active.remove(key)
            evidence.dependencies = self._dependencies(evidence, api)
            evidence.result = deepcopy(result)
            if outer:
                self._refresh(evidence, api, self.wall_clock() if now is None else now)
            self._merge(evidence)
            self._entries[key] = evidence
            return deepcopy(result)
        except BaseException:
            self._entries.clear()
            raise
        finally:
            if outer:
                self._reads.clear()
                self._read_bytes = 0
