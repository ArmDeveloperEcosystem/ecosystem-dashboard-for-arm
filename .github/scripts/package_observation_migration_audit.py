"""Read-only source audit for the strict package-observation migration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import exact_run_aggregation as exact
from package_result_policy import REGRESSION_DECISION_GROUPS, decision_group

AUDIT_SCHEMA = "arm-dashboard-package-observation-migration-audit"
AUDIT_VERSION = 1

_FALLBACK_RE = re.compile(
    r"steps\.[A-Za-z0-9_-]+\.outputs\.(?:regression_)?decision"
    r"\s*\|\|\s*(['\"])"
    r"(?P<decision>[a-z][a-z0-9_]*)\1",
    re.ASCII,
)
_ACTION_OUTPUT_VALUE_RE = re.compile(
    r"^\$\{\{\s*steps\.(?P<step>[A-Za-z0-9_-]+)\.outputs\."
    r"(?P<output>[A-Za-z0-9_-]+)\s*\}\}$",
    re.ASCII,
)
_SLUG_INPUT_RE = re.compile(
    r"^\$\{\{\s*steps\.(?P<step>[A-Za-z0-9_-]+)\.outputs\.package_slug"
    r"(?:\s*\|\|\s*'(?P<fallback>[A-Za-z0-9_.-]+)')?\s*\}\}$",
    re.ASCII,
)
_OBSERVATION_OUTPUT_RE = re.compile(
    r"^\$\{\{\s*steps\.(?P<step>[A-Za-z0-9_-]+)\.outputs\."
    r"package_observation_json\s*\}\}$",
    re.ASCII,
)
_WORKFLOW_CALL_OBSERVATION_RE = re.compile(
    r"^\$\{\{\s*jobs\.(?P<job>[A-Za-z0-9_-]+)\.outputs\."
    r"package_observation_json\s*\}\}$",
    re.ASCII,
)
_STEP_OUTPUT_EXPRESSION_RE = re.compile(
    r"^\$\{\{\s*(?P<reference>steps\.[A-Za-z0-9_-]+\.outputs\."
    r"[A-Za-z0-9_-]+)\s*\}\}$",
    re.ASCII,
)
_PLACEHOLDER_FALLBACK_RE = re.compile(
    r"\|\|\s*(['\"])(?:|unknown|n/a|na|none|null)\1",
    re.ASCII | re.IGNORECASE,
)
_NARRATIVE_FALLBACK_RE = re.compile(
    r"\|\|\s*(['\"])(?:regression result unavailable\.|"
    r"regression comparison summary unavailable\.|"
    r"no regression note recorded\.|)\1",
    re.ASCII | re.IGNORECASE,
)
_OUTPUT_ASSIGNMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$", re.ASCII
)
_LITERAL_VALUE_RE = re.compile(r"^[a-z][a-z0-9_]*$", re.ASCII)
_GITHUB_OUTPUT_TARGETS = frozenset({"$GITHUB_OUTPUT", "${GITHUB_OUTPUT}"})
_SHELL_PUNCTUATION = ";&|<>()"
_FUNCTION_START_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{\s*$",
    re.ASCII,
)


class AuditError(ValueError):
    """The repository cannot be audited deterministically."""


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditError(f"{label} must be a mapping")
    return value


def _steps(job: Mapping[str, Any], label: str) -> list[Mapping[str, Any]]:
    raw = job.get("steps")
    if not isinstance(raw, list):
        raise AuditError(f"{label} must have a steps list")
    result: list[Mapping[str, Any]] = []
    for index, step in enumerate(raw, start=1):
        result.append(_mapping(step, f"{label} step {index}"))
    return result


def _step_by_id(
    steps: Sequence[Mapping[str, Any]], step_id: str
) -> Mapping[str, Any] | None:
    matches = [step for step in steps if step.get("id") == step_id]
    if len(matches) > 1:
        raise AuditError(f"step id {step_id!r} is duplicated")
    return matches[0] if matches else None


def _steps_using(
    steps: Sequence[Mapping[str, Any]], reference: str
) -> list[Mapping[str, Any]]:
    return [step for step in steps if step.get("uses") == reference]


def _normalized_condition(value: object) -> str:
    if not isinstance(value, str):
        return ""
    condition = value.strip()
    if condition.startswith("${{") and condition.endswith("}}"):
        condition = condition[3:-2].strip()
    return condition


def _input_binds_slug(
    root: Path,
    steps: Sequence[Mapping[str, Any]],
    value: object,
    slug: str,
) -> bool:
    if value == slug:
        return True
    if not isinstance(value, str):
        return False
    match = _SLUG_INPUT_RE.fullmatch(value)
    if match is None:
        return False
    fallback = match.group("fallback")
    if fallback is not None and fallback != slug:
        return False
    source_step = _step_by_id(steps, match.group("step"))
    if source_step is None:
        return False
    return _step_literal_outputs(root, source_step, "package_slug") == (slug,)


def _exact_step_output_is_produced(
    root: Path,
    steps: Sequence[Mapping[str, Any]],
    value: object,
    references: Sequence[str],
) -> bool:
    if not isinstance(value, str):
        return False
    match = _STEP_OUTPUT_EXPRESSION_RE.fullmatch(value)
    if match is None:
        return False
    reference = match.group("reference")
    if reference not in references:
        return False
    parts = reference.split(".")
    source_step = _step_by_id(steps, parts[1])
    return source_step is not None and _step_emits_output(
        root, source_step, parts[3]
    )


def _observation_input_bindings_are_semantic(
    root: Path,
    steps: Sequence[Mapping[str, Any]],
    inputs: Mapping[str, Any],
) -> bool:
    required_references: dict[str, tuple[str, ...]] = {
        "run_status": ("steps.summary.outputs.overall_status",),
        "badge_status": ("steps.summary.outputs.badge_status",),
        "core_failed": ("steps.summary.outputs.core_failed",),
        "tests_passed": ("steps.summary.outputs.passed",),
        "tests_failed": ("steps.summary.outputs.failed",),
        "tests_skipped": ("steps.summary.outputs.skipped",),
        "duration_seconds": ("steps.summary.outputs.duration",),
        "regression_decision": (
            "steps.test6.outputs.decision",
            "steps.smoke.outputs.regression_decision",
        ),
        "regression_current_version": (
            "steps.test6.outputs.current_version",
            "steps.smoke.outputs.regression_current_version",
        ),
        "regression_latest_version": (
            "steps.test6.outputs.latest_version",
            "steps.smoke.outputs.regression_latest_version",
        ),
        "regression_next_installed_version": (
            "steps.test6.outputs.next_installed_version",
            "steps.smoke.outputs.regression_next_installed_version",
        ),
        "regression_result": (
            "steps.test6.outputs.regression_result",
            "steps.smoke.outputs.regression_result",
        ),
        "regression_comparison": (
            "steps.test6.outputs.comparison",
            "steps.smoke.outputs.regression_details",
        ),
    }
    for ordinal in range(1, 7):
        required_references[f"test{ordinal}_status"] = (
            f"steps.test{ordinal}.outputs.status",
            f"steps.smoke.outputs.test{ordinal}_status",
        )
        required_references[f"test{ordinal}_duration"] = (
            f"steps.test{ordinal}.outputs.duration",
            f"steps.smoke.outputs.test{ordinal}_duration",
        )
        name = inputs.get(f"test{ordinal}_name")
        valid_name = isinstance(name, str) and (
            name.startswith(f"Test {ordinal} -")
            if ordinal <= 5
            else name.startswith("Test 6 -") or name.startswith("Regression ")
        )
        if not valid_name:
            return False
    if any(
        not _exact_step_output_is_produced(
            root, steps, inputs.get(name), references
        )
        for name, references in required_references.items()
    ):
        return False
    package_name = inputs.get("package_name")
    package_version = inputs.get("package_version")
    return (
        isinstance(package_name, str)
        and bool(package_name.strip())
        and _exact_step_output_is_produced(
            root,
            steps,
            package_version,
            (
                "steps.version.outputs.version",
                "steps.smoke.outputs.version",
            ),
        )
    )


def _has_placeholder_fallback(value: object, *, narrative: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    placeholders = (
        {
            "",
            "regression result unavailable.",
            "regression comparison summary unavailable.",
            "no regression note recorded.",
        }
        if narrative
        else {"", "unknown", "n/a", "na", "none", "null"}
    )
    if value.strip().lower() in placeholders:
        return True
    pattern = _NARRATIVE_FALLBACK_RE if narrative else _PLACEHOLDER_FALLBACK_RE
    return pattern.search(value) is not None


def _local_action_path(root: Path, reference: str) -> Path | None:
    if not reference.startswith("./.github/actions/"):
        return None
    parts = PurePosixPath(reference.removeprefix("./")).parts
    if ".." in parts or parts[:2] != (".github", "actions"):
        raise AuditError(f"local action reference is unsafe: {reference}")
    return root.joinpath(*parts, "action.yml")


def _load_yaml(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise AuditError(f"unable to read {label}") from error
    try:
        return exact._yaml_mapping(raw, label)
    except exact.ContractError as error:
        raise AuditError(str(error)) from error


def _shell_tokens(line: str) -> tuple[str, ...]:
    candidate = line.rstrip()
    if candidate.endswith("\\"):
        candidate = candidate[:-1]
    lexer = shlex.shlex(
        candidate, posix=True, punctuation_chars=_SHELL_PUNCTUATION
    )
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        return tuple(lexer)
    except ValueError as error:
        excerpt = line.strip()[:120]
        raise AuditError(
            f"unable to parse a shell line used by the audit: {excerpt!r}"
        ) from error


def _is_shell_group_close(line: str) -> bool:
    return re.match(r"^}(?:\s|$)", line.strip(), re.ASCII) is not None


def _reachable_shell_sections(text: str) -> tuple[str, ...]:
    lines = text.splitlines()
    top_level: list[str] = []
    functions: dict[str, list[str]] = {}
    index = 0
    while index < len(lines):
        match = _FUNCTION_START_RE.fullmatch(lines[index])
        if match is None:
            top_level.append(lines[index])
            index += 1
            continue
        name = match.group("name")
        body: list[str] = []
        depth = 1
        index += 1
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped == "{":
                depth += 1
                body.append(lines[index])
            elif stripped == "}" and depth == 1:
                depth -= 1
                if depth == 0:
                    break
            elif _is_shell_group_close(stripped) and depth > 1:
                depth -= 1
                body.append(lines[index])
            else:
                body.append(lines[index])
            index += 1
        if depth != 0:
            raise AuditError(f"shell function {name!r} is not closed")
        functions.setdefault(name, []).extend(body)
        index += 1

    def called_functions(section_lines: Sequence[str]) -> set[str]:
        called: set[str] = set()
        for line in section_lines:
            if not any(name in line for name in functions):
                continue
            tokens = _shell_tokens(line)
            for token_index, token in enumerate(tokens):
                if token not in functions:
                    continue
                if token_index == 0 or tokens[token_index - 1] in {
                    ";",
                    "&&",
                    "||",
                    "|",
                    "then",
                    "do",
                    "else",
                    "if",
                    "!",
                }:
                    called.add(token)
        return called

    reachable: set[str] = set()
    pending = list(called_functions(top_level))
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(called_functions(functions[name]) - reachable)
    return ("\n".join(top_level),) + tuple(
        "\n".join(functions[name]) for name in sorted(reachable)
    )


def _command_assignments(
    tokens: Sequence[str],
) -> list[tuple[str, str | None]]:
    assignments: list[tuple[str, str | None]] = []
    for command_index, token in enumerate(tokens):
        if token not in {"echo", "printf"}:
            continue
        arguments: list[str] = []
        for argument in tokens[command_index + 1 :]:
            if argument in {";", "&&", "||", "|", ">", ">>"}:
                break
            arguments.append(argument)
        candidates: list[str] = []
        if token == "echo":
            while arguments and arguments[0] in {"-n", "-e", "-E"}:
                arguments.pop(0)
            if len(arguments) == 1:
                candidates.append(arguments[0])
        elif arguments:
            format_string = arguments[0]
            candidates.append(format_string.removesuffix("\\n"))
            if format_string in {"%s", "%s\\n"} and len(arguments) == 2:
                candidates.append(arguments[1])
        for candidate in candidates:
            match = _OUTPUT_ASSIGNMENT_RE.fullmatch(candidate)
            if match is not None:
                value = match.group("value")
                assignments.append(
                    (
                        match.group("name"),
                        value if _LITERAL_VALUE_RE.fullmatch(value) else None,
                    )
                )
    return assignments


def _github_output_transactions(
    text: str,
) -> tuple[tuple[tuple[str, str | None], ...], ...]:
    transactions: list[tuple[tuple[str, str | None], ...]] = []
    for section in _reachable_shell_sections(text):
        lines = section.splitlines()
        pending: list[tuple[str, str | None]] = []

        def flush_pending() -> None:
            if pending:
                transactions.append(tuple(pending))
                pending.clear()

        for line_index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "{":
                continue
            if "GITHUB_OUTPUT" not in line:
                continue
            tokens = _shell_tokens(line)
            closing_group_start = None
            if _is_shell_group_close(stripped) and tokens and tokens[0] == "}":
                closing_group_start = next(
                    (
                        index
                        for index in range(line_index - 1, -1, -1)
                        if lines[index].strip() == "{"
                    ),
                    None,
                )
            for redirect_index, token in enumerate(tokens):
                if token != ">>" or redirect_index + 1 >= len(tokens):
                    continue
                if tokens[redirect_index + 1] not in _GITHUB_OUTPUT_TARGETS:
                    continue
                if (
                    "}" in tokens[:redirect_index]
                    and closing_group_start is not None
                ):
                    flush_pending()
                    grouped_assignments: list[tuple[str, str | None]] = []
                    for grouped_line in lines[
                        closing_group_start + 1 : line_index
                    ]:
                        grouped_assignments.extend(
                            _command_assignments(_shell_tokens(grouped_line))
                        )
                    if grouped_assignments:
                        transactions.append(tuple(grouped_assignments))
                else:
                    assignments = _command_assignments(tokens[:redirect_index])
                    if not assignments:
                        continue
                    assignment_names = {name for name, _ in assignments}
                    pending_names = {name for name, _ in pending}
                    if "decision" in assignment_names and "decision" in pending_names:
                        flush_pending()
                    pending.extend(assignments)
                    pending_names = {name for name, _ in pending}
                    if {"decision", "status"}.issubset(pending_names):
                        flush_pending()
        flush_pending()
    return tuple(transactions)


def _github_output_writes(text: str) -> tuple[tuple[str, str | None], ...]:
    return tuple(
        assignment
        for transaction in _github_output_transactions(text)
        for assignment in transaction
    )


def _shell_code_contains(text: str, fragment: str) -> bool:
    for section in _reachable_shell_sections(text):
        for line in section.splitlines():
            if fragment not in line:
                continue
            if fragment in " ".join(_shell_tokens(line)):
                return True
    return False


def _shell_increments(text: str, variable: str) -> bool:
    expected = f"{variable}=$(({variable}+1))"
    for section in _reachable_shell_sections(text):
        for line in section.splitlines():
            if variable not in line:
                continue
            if expected in "".join(_shell_tokens(line)):
                return True
    return False


def _shell_assigns_literal(
    text: str, value: str, variable: str | None = None
) -> bool:
    variable_pattern = (
        re.escape(variable) if variable is not None else r"[A-Za-z_][A-Za-z0-9_]*"
    )
    assignment = re.compile(
        rf"^{variable_pattern}={re.escape(value)}$", re.ASCII
    )
    for section in _reachable_shell_sections(text):
        for line in section.splitlines():
            if value not in line:
                continue
            if any(assignment.fullmatch(token) for token in _shell_tokens(line)):
                return True
    return False


def _shell_variable_decision_status_pairs(
    text: str,
    decision_variable: str,
    status_variable: str,
) -> tuple[tuple[str, str], ...]:
    pairs: set[tuple[str, str]] = set()
    for section in _reachable_shell_sections(text):
        pending_decision: str | None = None
        for line in section.splitlines():
            tokens = _shell_tokens(line)
            events: list[tuple[str, str]] = []
            for token in tokens:
                match = _OUTPUT_ASSIGNMENT_RE.fullmatch(token)
                if match is None or not _LITERAL_VALUE_RE.fullmatch(
                    match.group("value")
                ):
                    continue
                if match.group("name") in {decision_variable, status_variable}:
                    events.append((match.group("name"), match.group("value")))
            for index, token in enumerate(tokens):
                if (
                    token == "set_test"
                    and index + 2 < len(tokens)
                    and tokens[index + 1] == "6"
                    and _LITERAL_VALUE_RE.fullmatch(tokens[index + 2])
                ):
                    events.append((status_variable, tokens[index + 2]))
            for name, value in events:
                if name == decision_variable:
                    pending_decision = value
                elif pending_decision is not None:
                    pairs.add((pending_decision, value))
                    pending_decision = None
    return tuple(sorted(pairs))


def _shared_smoke_literal_pairs(root: Path) -> tuple[tuple[str, str], ...]:
    action = "./.github/actions/run-missing-package-smoke"
    decision_binding = _action_output_binding(root, action, "regression_decision")
    status_binding = _action_output_binding(root, action, "test6_status")
    if decision_binding is None or status_binding is None:
        return ()
    decision_step, decision_variable = decision_binding
    status_step, status_variable = status_binding
    if (
        decision_step.get("id") != status_step.get("id")
        or _run_text(decision_step) != _run_text(status_step)
    ):
        return ()
    return _shell_variable_decision_status_pairs(
        _run_text(decision_step), decision_variable, status_variable
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_action_initializes_output_to(
    root: Path, reference: str, output: str, value: str
) -> bool:
    binding = _action_output_binding(root, reference, output)
    if binding is None:
        return False
    source_step, source_output = binding
    return _shell_assigns_literal(
        _run_text(source_step), value, variable=source_output
    )


def _action_output_binding(
    root: Path, reference: str, output: str
) -> tuple[Mapping[str, Any], str] | None:
    action_path = _local_action_path(root, reference)
    if action_path is None:
        return None
    action = _load_yaml(action_path, f"action {reference}")
    outputs = action.get("outputs", {})
    if not isinstance(outputs, Mapping):
        return None
    declaration = outputs.get(output)
    if not isinstance(declaration, Mapping):
        return None
    value = declaration.get("value")
    if not isinstance(value, str):
        return None
    match = _ACTION_OUTPUT_VALUE_RE.fullmatch(value)
    if match is None:
        return None
    runs = action.get("runs")
    if not isinstance(runs, Mapping) or runs.get("using") != "composite":
        return None
    action_steps = _steps(runs, f"action {reference}")
    source_step = _step_by_id(action_steps, match.group("step"))
    if source_step is None:
        return None
    return source_step, match.group("output")


def _required_action_inputs(root: Path, reference: str) -> frozenset[str]:
    action_path = _local_action_path(root, reference)
    if action_path is None:
        raise AuditError(f"required-input audit needs a local action: {reference}")
    action = _load_yaml(action_path, f"action {reference}")
    inputs = action.get("inputs")
    if not isinstance(inputs, Mapping):
        raise AuditError(f"action {reference} has no inputs mapping")
    required: set[str] = set()
    for name, declaration in inputs.items():
        if not isinstance(name, str) or not isinstance(declaration, Mapping):
            raise AuditError(f"action {reference} has an invalid input declaration")
        if declaration.get("required") is True:
            required.add(name)
    return frozenset(required)


def _run_text(step: Mapping[str, Any]) -> str:
    run = step.get("run", "")
    return run if isinstance(run, str) else ""


def _step_emits_output(
    root: Path,
    step: Mapping[str, Any],
    output: str,
    visited: frozenset[tuple[str, str]] = frozenset(),
) -> bool:
    if any(name == output for name, _ in _github_output_writes(_run_text(step))):
        return True
    uses = step.get("uses")
    if not isinstance(uses, str):
        return False
    identity = (uses, output)
    if identity in visited:
        raise AuditError(f"local action output cycle detected for {uses}#{output}")
    binding = _action_output_binding(root, uses, output)
    if binding is None:
        return False
    source_step, source_output = binding
    return _step_emits_output(
        root, source_step, source_output, visited | frozenset({identity})
    )


def _step_literal_outputs(
    root: Path,
    step: Mapping[str, Any],
    output: str,
    visited: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[str, ...]:
    values = {
        value
        for name, value in _github_output_writes(_run_text(step))
        if name == output and value is not None
    }
    uses = step.get("uses")
    if isinstance(uses, str):
        identity = (uses, output)
        if identity in visited:
            raise AuditError(f"local action output cycle detected for {uses}#{output}")
        binding = _action_output_binding(root, uses, output)
        if binding is not None:
            source_step, source_output = binding
            values.update(
                _step_literal_outputs(
                    root,
                    source_step,
                    source_output,
                    visited | frozenset({identity}),
                )
            )
    return tuple(sorted(values))


def _step_literal_pairs(
    root: Path,
    step: Mapping[str, Any],
    decision_output: str = "decision",
    status_output: str = "status",
    visited: frozenset[tuple[str, str, str]] = frozenset(),
) -> tuple[tuple[str, str], ...]:
    pairs: set[tuple[str, str]] = set()
    for transaction in _github_output_transactions(_run_text(step)):
        decisions = {
            value
            for name, value in transaction
            if name == decision_output and value is not None
        }
        statuses = {
            value
            for name, value in transaction
            if name == status_output and value is not None
        }
        if len(decisions) == 1 and len(statuses) == 1:
            pairs.add((next(iter(decisions)), next(iter(statuses))))

    uses = step.get("uses")
    if isinstance(uses, str):
        identity = (uses, decision_output, status_output)
        if identity in visited:
            raise AuditError(
                f"local action output cycle detected for {uses} pair"
            )
        decision_binding = _action_output_binding(root, uses, decision_output)
        status_binding = _action_output_binding(root, uses, status_output)
        if decision_binding is not None and status_binding is not None:
            decision_step, source_decision = decision_binding
            status_step, source_status = status_binding
            if (
                decision_step.get("id") == status_step.get("id")
                and _run_text(decision_step) == _run_text(status_step)
            ):
                pairs.update(
                    _step_literal_pairs(
                        root,
                        decision_step,
                        source_decision,
                        source_status,
                        visited | frozenset({identity}),
                    )
                )
    return tuple(sorted(pairs))


def _step_has_dynamic_output(
    root: Path,
    step: Mapping[str, Any],
    output: str,
    visited: frozenset[tuple[str, str]] = frozenset(),
) -> bool:
    if any(
        name == output and value is None
        for name, value in _github_output_writes(_run_text(step))
    ):
        return True
    uses = step.get("uses")
    if not isinstance(uses, str):
        return False
    identity = (uses, output)
    if identity in visited:
        raise AuditError(f"local action output cycle detected for {uses}#{output}")
    binding = _action_output_binding(root, uses, output)
    if binding is None:
        return False
    source_step, source_output = binding
    return _step_has_dynamic_output(
        root, source_step, source_output, visited | frozenset({identity})
    )


def _step_source(root: Path, step: Mapping[str, Any]) -> str:
    del root
    return _run_text(step)


def _step_output_source(
    root: Path,
    step: Mapping[str, Any],
    output: str,
    visited: frozenset[tuple[str, str]] = frozenset(),
) -> str:
    run = _run_text(step)
    if run:
        return run
    uses = step.get("uses")
    if not isinstance(uses, str):
        return ""
    identity = (uses, output)
    if identity in visited:
        raise AuditError(f"local action output cycle detected for {uses}#{output}")
    binding = _action_output_binding(root, uses, output)
    if binding is None:
        return ""
    source_step, source_output = binding
    return _step_output_source(
        root, source_step, source_output, visited | frozenset({identity})
    )


def _expected_raw_status(group: str) -> str:
    return {
        "passed": "passed",
        "failed": "failed",
        "deferred": "skipped",
        "not_applicable": "skipped",
        "baseline": "skipped",
    }[group]


def audit_repository(repository_root: Path) -> dict[str, Any]:
    root = repository_root.resolve(strict=True)
    topology = exact.discover_topology(root)
    registrations = [
        (definition.batch, registration)
        for definition in topology
        for registration in definition.packages
    ]

    approved_decisions = set().union(*REGRESSION_DECISION_GROUPS)
    emitter_workflows: list[str] = []
    custom_workflows: list[str] = []
    shared_smoke_workflows: list[str] = []
    emitter_contract_violations: list[str] = []
    emitter_missing_slug: list[str] = []
    emitter_slug_mismatch: list[str] = []
    shared_contract_violations: list[str] = []
    shared_smoke_literal_pair_contradictions: list[dict[str, str]] = []
    baseline_literal_skip: dict[str, list[str]] = {
        f"test{ordinal}": [] for ordinal in range(1, 6)
    }
    baseline_dynamic_skip: dict[str, list[str]] = {
        f"test{ordinal}": [] for ordinal in range(1, 6)
    }
    shared_smoke_baseline_skip_callers: list[str] = []
    generic_source_missing_baseline_facts: list[str] = []
    missing_package_observation_output: list[str] = []
    missing_package_observation_step: list[str] = []
    missing_workflow_call_observation_output: list[str] = []
    invalid_workflow_call_observation_output: list[str] = []
    invalid_package_observation_contract: list[str] = []
    invalid_package_observation_input_bindings: list[str] = []
    unsafe_package_version_fallback: list[str] = []
    unsafe_regression_narrative_fallback: list[str] = []
    cohort_shared_smoke: list[str] = []
    cohort_emitter_only: list[str] = []
    cohort_generic_source: list[str] = []
    cohort_fully_custom: list[str] = []
    missing_test_steps: dict[str, list[str]] = {
        f"test{ordinal}": [] for ordinal in range(1, 7)
    }
    invalid_test_names: dict[str, list[str]] = {
        f"test{ordinal}": [] for ordinal in range(1, 7)
    }
    missing_test_status: dict[str, list[str]] = {
        f"test{ordinal}": [] for ordinal in range(1, 7)
    }
    missing_test_duration: dict[str, list[str]] = {
        f"test{ordinal}": [] for ordinal in range(1, 7)
    }
    summary_missing_duration_reference: dict[str, list[str]] = {
        f"test{ordinal}": [] for ordinal in range(1, 7)
    }
    missing_summary_step: list[str] = []
    missing_summary_outputs: dict[str, list[str]] = {
        output: []
        for output in (
            "overall_status",
            "badge_status",
            "core_failed",
            "passed",
            "failed",
            "skipped",
            "duration",
        )
    }
    decision_token_counts: Counter[str] = Counter()
    fallback_counts: Counter[str] = Counter()
    unapproved_decision_tokens: set[str] = set()
    unsafe_fallback_workflows: list[str] = []
    no_literal_decision: list[str] = []
    literal_pair_contradictions: list[dict[str, object]] = []
    package_manager_workflows: list[str] = []
    package_manager_missing_decision: list[str] = []
    package_manager_non_skipped_status: list[str] = []
    package_manager_missing_baseline_guard: list[str] = []
    package_manager_missing_explicit_skip_counter: list[str] = []
    package_manager_summary_omits_test6: list[str] = []
    non_package_manager_missing_baseline_guard: list[str] = []
    summary_omits_test6_status: list[str] = []
    legacy_batch_collector_workflows: list[str] = []
    missing_strict_batch_collector: list[str] = []
    invalid_strict_batch_collector: list[str] = []

    observation_action = "./.github/actions/emit-package-observation"
    required_observation_inputs = _required_action_inputs(root, observation_action)
    shared_smoke_pairs = _shared_smoke_literal_pairs(root)
    shared_smoke_literal_pair_contradictions = [
        {
            "decision": decision,
            "status": status,
            "expected_status": _expected_raw_status(decision_group(decision)),
        }
        for decision, status in shared_smoke_pairs
        if decision in approved_decisions
        and status != _expected_raw_status(decision_group(decision))
    ]

    strict_batch_action = "./.github/actions/collect-batch-observations"
    for definition in topology:
        batch_path = root / definition.workflow_path
        batch_payload = _load_yaml(batch_path, definition.workflow_path)
        batch_jobs = _mapping(
            batch_payload.get("jobs"), f"{definition.workflow_path} jobs"
        )
        for job_value in batch_jobs.values():
            if not isinstance(job_value, Mapping) or not isinstance(
                job_value.get("steps"), list
            ):
                continue
            if any(
                step.get("uses") == "./.github/actions/collect-batch-results"
                for step in _steps(job_value, definition.workflow_path)
            ):
                legacy_batch_collector_workflows.append(definition.workflow_path)
                break
        strict_steps = [
            (job_value, step)
            for job_value in batch_jobs.values()
            if isinstance(job_value, Mapping)
            and isinstance(job_value.get("steps"), list)
            for step in _steps(job_value, definition.workflow_path)
            if step.get("uses") == strict_batch_action
        ]
        if not strict_steps:
            missing_strict_batch_collector.append(definition.workflow_path)
        elif len(strict_steps) != 1:
            invalid_strict_batch_collector.append(definition.workflow_path)
        else:
            strict_job, strict_step = strict_steps[0]
            strict_inputs = strict_step.get("with", {})
            expected_strict_inputs = {
                "batch_number": str(definition.batch),
                "orchestration_id": "${{ inputs.orchestration_id }}",
                "dispatch_nonce": "${{ inputs.dispatch_nonce }}",
                "package_observations_json": "${{ toJson(needs) }}",
            }
            action_path = _local_action_path(root, strict_batch_action)
            action_contract_is_valid = False
            if action_path is not None and action_path.is_file():
                strict_action = _load_yaml(action_path, "strict batch action")
                action_outputs = strict_action.get("outputs", {})
                action_contract_is_valid = (
                    isinstance(action_outputs, Mapping)
                    and set(action_outputs) == {"artifact_path"}
                    and _required_action_inputs(root, strict_batch_action)
                    == frozenset(expected_strict_inputs)
                    and _step_emits_output(
                        root, strict_step, "artifact_path"
                    )
                )
            strict_job_steps = _steps(strict_job, definition.workflow_path)
            uploaders = [
                step
                for step in strict_job_steps
                if isinstance(step.get("uses"), str)
                and str(step["uses"]).startswith("actions/upload-artifact@")
            ]
            uploader_is_valid = False
            if len(uploaders) == 1:
                uploader = uploaders[0]
                uploader_inputs = uploader.get("with", {})
                uploader_is_valid = (
                    strict_job_steps.index(uploader)
                    > strict_job_steps.index(strict_step)
                    and _normalized_condition(uploader.get("if"))
                    in {"", "always()"}
                    and uploader.get("continue-on-error") in {None, False}
                    and isinstance(uploader_inputs, Mapping)
                    and uploader_inputs.get("name")
                    == f"batch{definition.batch}-test-results"
                    and uploader_inputs.get("path")
                    == "${{ steps.collect.outputs.artifact_path }}"
                )
            if not (
                strict_step.get("id") == "collect"
                and _normalized_condition(strict_step.get("if"))
                in {"", "always()"}
                and strict_step.get("continue-on-error") in {None, False}
                and isinstance(strict_inputs, Mapping)
                and dict(strict_inputs) == expected_strict_inputs
                and action_contract_is_valid
                and uploader_is_valid
            ):
                invalid_strict_batch_collector.append(definition.workflow_path)

    for batch, registration in registrations:
        slug = registration.package_slug
        workflow_path = root / registration.workflow_path
        payload = _load_yaml(workflow_path, registration.workflow_path)
        triggers = payload.get("on")
        workflow_call = (
            triggers.get("workflow_call")
            if isinstance(triggers, Mapping)
            else None
        )
        workflow_outputs = (
            workflow_call.get("outputs")
            if isinstance(workflow_call, Mapping)
            else None
        )
        exported_observation = (
            workflow_outputs.get("package_observation_json")
            if isinstance(workflow_outputs, Mapping)
            else None
        )
        if exported_observation is None:
            missing_workflow_call_observation_output.append(slug)
        else:
            exported_value = (
                exported_observation.get("value")
                if isinstance(exported_observation, Mapping)
                else None
            )
            export_match = (
                _WORKFLOW_CALL_OBSERVATION_RE.fullmatch(exported_value)
                if isinstance(exported_value, str)
                else None
            )
            if (
                export_match is None
                or export_match.group("job") != registration.called_job
            ):
                invalid_workflow_call_observation_output.append(slug)
        jobs = _mapping(payload.get("jobs"), f"{registration.workflow_path} jobs")
        job = _mapping(
            jobs.get(registration.called_job),
            f"{registration.workflow_path} job {registration.called_job}",
        )
        job_outputs = _mapping(
            job.get("outputs"), f"{registration.workflow_path} job outputs"
        )
        if "package_observation_json" not in job_outputs:
            missing_package_observation_output.append(slug)
        package_version_output = job_outputs.get("package_version")
        if _has_placeholder_fallback(package_version_output):
            unsafe_package_version_fallback.append(slug)
        narrative_outputs = (
            job_outputs.get("regression_result"),
            job_outputs.get("regression_comparison"),
        )
        if any(
            _has_placeholder_fallback(value, narrative=True)
            for value in narrative_outputs
        ):
            unsafe_regression_narrative_fallback.append(slug)
        steps = _steps(job, registration.workflow_path)
        observation_steps = _steps_using(steps, observation_action)
        if len(observation_steps) > 1:
            raise AuditError(
                f"{registration.workflow_path} has duplicate observation emitters"
            )
        if not observation_steps:
            missing_package_observation_step.append(slug)
        else:
            observation_step = observation_steps[0]
            observation_inputs = observation_step.get("with", {})
            output_binding = job_outputs.get("package_observation_json")
            binding_match = (
                _OBSERVATION_OUTPUT_RE.fullmatch(output_binding)
                if isinstance(output_binding, str)
                else None
            )
            observation_contract_is_valid = (
                isinstance(observation_inputs, Mapping)
                and required_observation_inputs.issubset(observation_inputs)
                and _normalized_condition(observation_step.get("if")) == "always()"
                and binding_match is not None
                and binding_match.group("step") == observation_step.get("id")
                and _action_output_binding(
                    root, observation_action, "package_observation_json"
                )
                is not None
                and _input_binds_slug(
                    root,
                    steps,
                    observation_inputs.get("package_slug"),
                    slug,
                )
            )
            if not observation_contract_is_valid:
                invalid_package_observation_contract.append(slug)
            elif not _observation_input_bindings_are_semantic(
                root, steps, observation_inputs
            ):
                invalid_package_observation_input_bindings.append(slug)
        emitters = _steps_using(
            steps, "./.github/actions/emit-package-result"
        )
        shared_steps = _steps_using(
            steps, "./.github/actions/run-missing-package-smoke"
        )
        if len(emitters) > 1:
            raise AuditError(f"{registration.workflow_path} has duplicate emitters")
        if len(shared_steps) > 1:
            raise AuditError(
                f"{registration.workflow_path} has duplicate shared smoke steps"
            )
        emitter = emitters[0] if emitters else None
        shared = shared_steps[0] if shared_steps else None
        emitter_is_valid = False
        if emitter is not None:
            emitter_workflows.append(slug)
            inputs = emitter.get("with", {})
            emitter_is_valid = (
                emitter.get("id") == "summary"
                and _normalized_condition(emitter.get("if")) == "always()"
            )
            if not emitter_is_valid:
                emitter_contract_violations.append(slug)
            if not isinstance(inputs, Mapping) or not inputs.get("package_slug"):
                emitter_missing_slug.append(slug)
            elif not _input_binds_slug(
                root, steps, inputs.get("package_slug"), slug
            ):
                emitter_slug_mismatch.append(slug)
        else:
            custom_workflows.append(slug)
        shared_is_valid = False
        if shared is not None:
            shared_smoke_workflows.append(slug)
            inputs = shared.get("with", {})
            required_shared_outputs = tuple(
                f"test{ordinal}_{field}"
                for ordinal in range(1, 7)
                for field in ("status", "duration")
            ) + ("regression_decision",)
            shared_is_valid = (
                shared.get("id") == "smoke"
                and isinstance(inputs, Mapping)
                and _input_binds_slug(
                    root, steps, inputs.get("package_slug"), slug
                )
                and not _normalized_condition(shared.get("if"))
                and all(
                    _step_emits_output(root, shared, output)
                    for output in required_shared_outputs
                )
                and bool(shared_smoke_pairs)
            )
            if not shared_is_valid:
                shared_contract_violations.append(slug)
            elif any(
                _local_action_initializes_output_to(
                    root,
                    "./.github/actions/run-missing-package-smoke",
                    f"test{ordinal}_status",
                    "skipped",
                )
                for ordinal in range(1, 6)
            ):
                shared_smoke_baseline_skip_callers.append(slug)

        test6: Mapping[str, Any] | None = None
        if not shared_is_valid:
            for ordinal in range(1, 7):
                test_id = f"test{ordinal}"
                step = _step_by_id(steps, test_id)
                if step is None:
                    missing_test_steps[test_id].append(slug)
                    continue
                if ordinal == 6:
                    test6 = step
                name = step.get("name")
                valid_name = isinstance(name, str) and (
                    name.startswith(f"Test {ordinal} -")
                    if ordinal <= 5
                    else name.startswith("Test 6 -")
                    or name.startswith("Regression ")
                    or name.startswith("Regression applicability ")
                )
                if not valid_name:
                    invalid_test_names[test_id].append(slug)
                if not _step_emits_output(root, step, "status"):
                    missing_test_status[test_id].append(slug)
                elif ordinal <= 5 and "skipped" in _step_literal_outputs(
                    root, step, "status"
                ):
                    baseline_literal_skip[test_id].append(slug)
                if (
                    ordinal <= 5
                    and _step_has_dynamic_output(root, step, "status")
                    and _shell_assigns_literal(
                        _step_output_source(root, step, "status"), "skipped"
                    )
                ):
                    baseline_dynamic_skip[test_id].append(slug)
                if not _step_emits_output(root, step, "duration"):
                    missing_test_duration[test_id].append(slug)

        uses_generic_source = (
            test6 is not None
            and test6.get("uses")
            == "./.github/actions/generic-source-regression-check"
        )
        if uses_generic_source:
            generic_inputs = test6.get("with", {})
            required_baseline_inputs = {
                f"test{ordinal}_status" for ordinal in range(1, 6)
            }
            if (
                not isinstance(generic_inputs, Mapping)
                or not required_baseline_inputs.issubset(generic_inputs)
            ):
                generic_source_missing_baseline_facts.append(slug)

        if shared_is_valid:
            cohort_shared_smoke.append(slug)
        elif emitter_is_valid:
            cohort_emitter_only.append(slug)
        elif uses_generic_source:
            cohort_generic_source.append(slug)
        else:
            cohort_fully_custom.append(slug)

        summary = _step_by_id(steps, "summary")
        if summary is None:
            missing_summary_step.append(slug)
            summary_source = ""
            summary_mentions_test6 = False
        else:
            summary_source = _step_source(root, summary)
            for output in missing_summary_outputs:
                if not _step_emits_output(root, summary, output):
                    missing_summary_outputs[output].append(slug)
            summary_mentions_test6 = _shell_code_contains(
                summary_source, "steps.test6.outputs.status"
            )
            if not emitter_is_valid:
                if not summary_mentions_test6:
                    summary_omits_test6_status.append(slug)
                for ordinal in range(1, 7):
                    reference = f"steps.test{ordinal}.outputs.duration"
                    if not _shell_code_contains(summary_source, reference):
                        summary_missing_duration_reference[f"test{ordinal}"].append(
                            slug
                        )

        regression_output = job_outputs.get("regression_decision")
        if not isinstance(regression_output, str):
            raise AuditError(
                f"{registration.workflow_path} has no regression_decision output"
            )
        fallbacks = [
            match.group("decision")
            for match in _FALLBACK_RE.finditer(regression_output)
        ]
        if len(fallbacks) != 1:
            raise AuditError(
                f"{registration.workflow_path} must have one decision fallback"
            )
        fallback = fallbacks[0]
        fallback_counts[fallback] += 1
        if fallback != "not_configured":
            unsafe_fallback_workflows.append(slug)

        if test6 is not None:
            decisions = _step_literal_outputs(root, test6, "decision")
            statuses = _step_literal_outputs(root, test6, "status")
            decision_status_pairs = _step_literal_pairs(root, test6)
            decision_token_counts.update(decisions)
            unapproved_decision_tokens.update(
                decision for decision in decisions if decision not in approved_decisions
            )
            if not decisions:
                no_literal_decision.append(slug)
            invalid_pairs = [
                {
                    "decision": decision,
                    "status": status,
                    "expected_status": _expected_raw_status(
                        decision_group(decision)
                    ),
                }
                for decision, status in decision_status_pairs
                if decision in approved_decisions
                and status != _expected_raw_status(decision_group(decision))
            ]
            if invalid_pairs:
                literal_pair_contradictions.append(
                    {
                        "batch": batch,
                        "package_slug": slug,
                        "invalid_pairs": invalid_pairs,
                    }
                )
            name_marks_package_manager = "package manager" in str(
                test6.get("name", "")
            ).lower()
            decision_marks_package_manager = (
                "not_applicable_package_manager" in decisions
                or fallback == "not_applicable_package_manager"
            )
            is_package_manager = (
                name_marks_package_manager or decision_marks_package_manager
            )
            if is_package_manager:
                package_manager_workflows.append(slug)
                if not {
                    "baseline_failed",
                    "baseline_install_failed",
                }.intersection(decisions):
                    package_manager_missing_baseline_guard.append(slug)
                if "not_applicable_package_manager" not in decisions:
                    package_manager_missing_decision.append(slug)
                if statuses != ("skipped",):
                    package_manager_non_skipped_status.append(slug)
                if not emitter_is_valid:
                    has_skip_counter = (
                        summary_mentions_test6
                        and _shell_increments(summary_source, "SKIPPED")
                        and summary is not None
                        and _step_emits_output(root, summary, "skipped")
                    )
                    if not has_skip_counter:
                        package_manager_missing_explicit_skip_counter.append(slug)
                    if not summary_mentions_test6:
                        package_manager_summary_omits_test6.append(slug)
            elif not uses_generic_source and not {
                "baseline_failed",
                "baseline_install_failed",
            }.intersection(decisions):
                non_package_manager_missing_baseline_guard.append(slug)

    cohort_members = (
        cohort_shared_smoke
        + cohort_emitter_only
        + cohort_generic_source
        + cohort_fully_custom
    )
    if len(cohort_members) != len(registrations) or len(set(cohort_members)) != len(
        registrations
    ):
        raise AuditError("migration cohorts are not an exact package partition")

    critical_sources = (
        ".github/actions/collect-batch-results/action.yml",
        ".github/actions/emit-package-observation/action.yml",
        ".github/actions/emit-package-result/action.yml",
        ".github/actions/generic-source-regression-check/action.yml",
        ".github/actions/run-missing-package-smoke/action.yml",
        ".github/scripts/download-with-fallback.sh",
        ".github/scripts/exact_run_aggregation.py",
        ".github/scripts/package_observation_migration_audit.py",
        ".github/scripts/package_observation.py",
        ".github/scripts/package_result_policy.py",
    )
    existing_critical_sources = list(critical_sources)
    strict_batch_action_path = _local_action_path(root, strict_batch_action)
    if strict_batch_action_path is not None and strict_batch_action_path.is_file():
        existing_critical_sources.append(
            str(strict_batch_action_path.relative_to(root))
        )

    remediation = {
        "baseline_literal_skip": {
            key: sorted(value)
            for key, value in baseline_literal_skip.items()
            if value
        },
        "baseline_dynamic_skip": {
            key: sorted(value)
            for key, value in baseline_dynamic_skip.items()
            if value
        },
        "emitter_contract_violations": sorted(emitter_contract_violations),
        "emitter_missing_slug": sorted(emitter_missing_slug),
        "emitter_slug_mismatch": sorted(emitter_slug_mismatch),
        "invalid_test_names": {
            key: sorted(value) for key, value in invalid_test_names.items() if value
        },
        "legacy_batch_collector_workflows": sorted(
            set(legacy_batch_collector_workflows)
        ),
        "literal_pair_contradictions": sorted(
            literal_pair_contradictions, key=lambda item: str(item["package_slug"])
        ),
        "missing_summary_step": sorted(missing_summary_step),
        "missing_summary_outputs": {
            key: sorted(value)
            for key, value in missing_summary_outputs.items()
            if value
        },
        "missing_package_observation_output": sorted(
            missing_package_observation_output
        ),
        "missing_test_duration": {
            key: sorted(value) for key, value in missing_test_duration.items() if value
        },
        "missing_test_status": {
            key: sorted(value) for key, value in missing_test_status.items() if value
        },
        "missing_test_steps": {
            key: sorted(value) for key, value in missing_test_steps.items() if value
        },
        "no_literal_decision": sorted(no_literal_decision),
        "package_manager_missing_decision": sorted(
            package_manager_missing_decision
        ),
        "package_manager_missing_baseline_guard": sorted(
            package_manager_missing_baseline_guard
        ),
        "package_manager_missing_explicit_skip_counter": sorted(
            package_manager_missing_explicit_skip_counter
        ),
        "package_manager_non_skipped_status": sorted(
            package_manager_non_skipped_status
        ),
        "package_manager_summary_omits_test6": sorted(
            package_manager_summary_omits_test6
        ),
        "summary_missing_duration_reference": {
            key: sorted(value)
            for key, value in summary_missing_duration_reference.items()
            if value
        },
        "shared_contract_violations": sorted(shared_contract_violations),
        "shared_smoke_literal_pair_contradictions": (
            shared_smoke_literal_pair_contradictions
        ),
        "shared_smoke_baseline_skip_callers": sorted(
            shared_smoke_baseline_skip_callers
        ),
        "generic_source_missing_baseline_facts": sorted(
            generic_source_missing_baseline_facts
        ),
        "invalid_package_observation_contract": sorted(
            invalid_package_observation_contract
        ),
        "invalid_package_observation_input_bindings": sorted(
            invalid_package_observation_input_bindings
        ),
        "invalid_strict_batch_collector": sorted(
            invalid_strict_batch_collector
        ),
        "invalid_workflow_call_observation_output": sorted(
            invalid_workflow_call_observation_output
        ),
        "missing_package_observation_step": sorted(
            missing_package_observation_step
        ),
        "missing_strict_batch_collector": sorted(
            missing_strict_batch_collector
        ),
        "missing_workflow_call_observation_output": sorted(
            missing_workflow_call_observation_output
        ),
        "non_package_manager_missing_baseline_guard": sorted(
            non_package_manager_missing_baseline_guard
        ),
        "summary_omits_test6_status": sorted(summary_omits_test6_status),
        "unsafe_package_version_fallback": sorted(
            unsafe_package_version_fallback
        ),
        "unsafe_regression_narrative_fallback": sorted(
            unsafe_regression_narrative_fallback
        ),
        "unsafe_fallback_workflows": sorted(unsafe_fallback_workflows),
        "unapproved_decision_tokens": sorted(unapproved_decision_tokens),
    }
    return {
        "schema": AUDIT_SCHEMA,
        "version": AUDIT_VERSION,
        "cutover_authorized": False,
        "totals": {
            "batches": len(topology),
            "packages": len(registrations),
            "custom_summary_workflows": len(custom_workflows),
            "emitter_workflows": len(emitter_workflows),
            "shared_smoke_workflows": len(shared_smoke_workflows),
            "package_manager_workflows": len(package_manager_workflows),
        },
        "approved_decisions": sorted(approved_decisions),
        "audited_source_digests": {
            path: _sha256_file(root / path) for path in existing_critical_sources
        },
        "decision_token_counts": dict(sorted(decision_token_counts.items())),
        "fallback_counts": dict(sorted(fallback_counts.items())),
        "required_activation_gates": [
            "native_arm64_shadow_validation",
            "supply_chain_lock_reseal_after_workflow_bytes_stabilize",
        ],
        "migration_cohorts": {
            "shared_smoke": sorted(cohort_shared_smoke),
            "emitter_only": sorted(cohort_emitter_only),
            "generic_source": sorted(cohort_generic_source),
            "fully_custom": sorted(cohort_fully_custom),
        },
        "remediation": remediation,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="exit 1 when any migration remediation remains",
    )
    parser.add_argument(
        "--require-activation-ready",
        action="store_true",
        help=(
            "exit 3 unless static remediation is empty and independently "
            "verified Arm64 shadow and supply-chain reseal evidence authorizes cutover"
        ),
    )
    return parser


def report_has_findings(report: Mapping[str, Any]) -> bool:
    remediation = report.get("remediation")
    if not isinstance(remediation, Mapping):
        raise AuditError("audit report has no remediation mapping")
    return any(bool(value) for value in remediation.values())


def report_is_activation_ready(report: Mapping[str, Any]) -> bool:
    report_has_findings(report)
    if report.get("cutover_authorized") is not False:
        raise AuditError("the source-only audit cannot authorize cutover")
    return False


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = audit_repository(args.repository_root)
        encoded = canonical_json(report) + "\n"
        if args.output is None:
            sys.stdout.write(encoded)
        else:
            args.output.write_text(encoded, encoding="utf-8")
        if args.require_activation_ready and not report_is_activation_ready(report):
            return 3
        return 1 if args.require_clean and report_has_findings(report) else 0
    except (AuditError, exact.ContractError, OSError) as error:
        print(f"package observation migration audit error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
