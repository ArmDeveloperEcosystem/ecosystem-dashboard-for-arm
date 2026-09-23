"""Word, JSON, and CSV reporting with linked, scoped authoritative evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

STATUS = {
    "supported": "Arm64 supported",
    "gap": "Arm64 support gap",
    "unknown": "Arm64 support unclear",
}


def clean(value):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))


def hyperlink(paragraph, label, url):
    if not str(url).startswith("https://"):
        paragraph.add_run(clean(label))
        return
    relation = paragraph.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), relation)
    run = OxmlElement("w:r")
    prop = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "176A84")
    prop.append(color)
    run.append(prop)
    text = OxmlElement("w:t")
    text.text = clean(label)
    run.append(text)
    link.append(run)
    paragraph._p.append(link)


def table(doc, headers, rows, widths):
    t = doc.add_table(rows=1, cols=len(headers))
    t.autofit = False
    t.style = "Table Grid"
    pr = t._tbl.tblPr
    for tag, attrs in (
        ("tblW", {"w": 9360, "type": "dxa"}),
        ("tblInd", {"w": 120, "type": "dxa"}),
    ):
        elem = pr.find(qn("w:" + tag))
        if elem is None:
            elem = OxmlElement("w:" + tag)
            pr.append(elem)
        for key, value in attrs.items():
            elem.set(qn("w:" + key), str(value))
    margins = OxmlElement("w:tblCellMar")
    for key, value in {"top": 80, "bottom": 80, "start": 120, "end": 120}.items():
        child = OxmlElement("w:" + key)
        child.set(qn("w:w"), str(value))
        child.set(qn("w:type"), "dxa")
        margins.append(child)
    pr.append(margins)
    for i, width in enumerate(widths):
        t._tbl.tblGrid.gridCol_lst[i].set(qn("w:w"), str(width))
    for cell, value in zip(t.rows[0].cells, headers):
        cell.text = clean(value)
        shade = OxmlElement("w:shd")
        shade.set(qn("w:fill"), "F2F4F7")
        cell._tc.get_or_add_tcPr().append(shade)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    repeat = OxmlElement("w:tblHeader")
    t.rows[0]._tr.get_or_add_trPr().append(repeat)
    for values in rows:
        for cell, value in zip(t.add_row().cells, values):
            cell.text = clean(value)
    for row in t.rows:
        cant_split = OxmlElement("w:cantSplit")
        row._tr.get_or_add_trPr().append(cant_split)
        for cell, width in zip(row.cells, widths):
            cell.width = Inches(width / 1440)
            cell._tc.get_or_add_tcPr().find(qn("w:tcW")).set(qn("w:w"), str(width))
            for p in cell.paragraphs:
                p.style = doc.styles["Table Text"]
    return t


def document_style(doc):
    """standard_business_brief + memo_masthead; named compact table/citation override."""
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = section.left_margin = (
        section.right_margin
    ) = Inches(1)
    section.header_distance = section.footer_distance = Inches(0.492)
    tokens = {
        "Normal": (11, "202B33", 0, 6, 1.10),
        "Title": (26, "123B4A", 0, 8, 1.10),
        "Subtitle": (12, "536873", 0, 10, 1.10),
        "Heading 1": (16, "2E74B5", 16, 8, 1.10),
        "Heading 2": (13, "2E74B5", 12, 6, 1.10),
        "Heading 3": (12, "1F4D78", 8, 4, 1.10),
        "Table Text": (9, "202B33", 0, 4, 1.10),
        "Evidence": (9, "536873", 4, 4, 1.10),
        "Metadata": (10, "536873", 0, 3, 1.10),
    }
    for name, (size, color, before, after, line) in tokens.items():
        style = (
            doc.styles[name] if name in doc.styles else doc.styles.add_style(name, 1)
        )
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = line
        style.paragraph_format.widow_control = True
        if name.startswith("Heading"):
            style.font.bold = True
            style.paragraph_format.keep_with_next = True
    header = section.header.paragraphs[0]
    header.style = "Metadata"
    header.text = "ARM LINUX ECOSYSTEM  |  INTERNAL OPPORTUNITY REVIEW"
    footer = section.footer.paragraphs[0]
    footer.style = "Metadata"
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run("Internal research PoC  |  Page ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    doc.core_properties.title = "Linux Arm64 support gap discovery"
    doc.core_properties.subject = (
        "Evidence-backed internal enablement opportunity review"
    )
    doc.core_properties.author = "Arm Linux Ecosystem PoC"


def write_reports(summary):
    paths = summary["report_paths"]
    Path(paths["json"]).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with open(paths["csv"], "w", newline="", encoding="utf-8") as stream:
        fields = [
            "candidate_id",
            "status",
            "scope",
            "checked_at",
            "catalog_tracked",
            "investigated_before",
            "recommended_action",
            "evidence_urls",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for finding in summary["findings"]:
            values = {key: finding.get(key, "") for key in fields}
            values["evidence_urls"] = " | ".join(e["url"] for e in finding["evidence"])
            # Prevent source text from becoming a spreadsheet formula when opened.
            writer.writerow(
                {
                    k: "'" + v
                    if isinstance(v, str) and v.startswith(("=", "+", "-", "@"))
                    else v
                    for k, v in values.items()
                }
            )
    doc = Document()
    document_style(doc)
    doc.add_paragraph("Linux Arm64\nsupport gap discovery", "Title")
    doc.add_paragraph("Evidence-backed opportunities for internal review", "Subtitle")
    doc.add_paragraph(
        "Observed: " + summary["generated_at"] + "  |  Run: " + summary["run_id"],
        "Metadata",
    )
    doc.add_paragraph(
        "Scope: selected project repositories and exact container tags. Evidence is authoritative for each selected repository; upstream ownership is not independently verified. No downloaded code was executed.",
        "Metadata",
    )
    doc.add_heading("Executive assessment", level=1)
    c = summary["counts"]
    doc.add_paragraph(
        f"This run investigated {c['investigated']} distribution scopes: {c['gap']} potential Linux Arm64 support gaps, {c['unknown']} unclear results, and {c['supported']} supported results. Findings are distribution-specific evidence for human prioritization; they do not establish project-wide incompatibility."
    )
    table(
        doc,
        ["Supported", "Potential gaps", "Unclear", "Already cataloged"],
        [[c["supported"], c["gap"], c["unknown"], c["catalog_tracked"]]],
        [2340] * 4,
    )
    doc.add_paragraph(
        f"New investigations: {c['newly_investigated']}. Refreshed investigations: {c['refreshed']}. Saved observations: {c['saved_observations']}. Metadata requests: {c['requests']}. Collection/review issues: {c['failures']}."
    )
    if summary.get("retained_findings"):
        retained = summary["retained_findings"]
        doc.add_paragraph(
            f"Historical context: {len(retained)} previously investigated scopes were retained without rechecking, including {sum(f['status'] == 'gap' for f in retained)} previously observed gaps. Their original evidence dates are shown in saved history; they are excluded from this run's findings counts."
        )
    doc.add_paragraph(summary["ai_review"]["disclosure"])
    doc.add_heading("How to interpret this report", level=1)
    doc.add_paragraph(
        "Supported means at least one artifact published by the selected repository, or a runtime platform descriptor for the selected tag, explicitly identifies Linux Arm64. This does not cover every project component. A gap requires a complete, interpretable inventory for the exact scope. Unclear means the evidence cannot establish either outcome. Catalog membership and prior investigation are separate tracking facts."
    )
    doc.add_paragraph(
        "Priority: review scoped gaps first, then resolve unknown evidence. Reuse saved investigations before opening new follow-up work. No finding automatically updates the public dashboard or contacts a maintainer."
    )
    doc.add_heading("Findings and recommended action", level=1)
    if not summary["findings"]:
        doc.add_paragraph(
            "No candidates were investigated in this run. Review saved history, refresh dates, and skipped work below; prior findings have not been reclassified."
        )
    for f in sorted(
        summary["findings"],
        key=lambda value: (
            {"gap": 0, "unknown": 1, "supported": 2}[value["status"]],
            value["name"],
        ),
    ):
        doc.add_heading(f["name"] + " | " + STATUS[f["status"]], level=2)
        doc.add_paragraph(clean(f["scope"]), "Metadata")
        tracking = (
            "Yes"
            if f["catalog_tracked"] is True
            else "No exact repository URL match"
            if f["catalog_tracked"] is False
            else "Comparison unavailable"
        )
        doc.add_paragraph(
            f"Cataloged: {tracking}. Prior investigation: {'Yes' if f['investigated_before'] else 'No'}. Next refresh: {f['next_check_at']}.",
            "Metadata",
        )
        if (
            f["source"] == "github"
            and f.get("metadata", {}).get("stargazers_count") is not None
        ):
            doc.add_paragraph(
                f"GitHub stars: {f['metadata']['stargazers_count']:,}. Observed: {f['checked_at']}.",
                "Metadata",
            )
        if f.get("selection_reason"):
            doc.add_paragraph(f["selection_reason"], "Metadata")
        doc.add_paragraph(clean(f["reason"]))
        p = doc.add_paragraph()
        p.add_run("Recommended action: ").bold = True
        p.add_run(clean(f["recommended_action"]))
        cited = [
            e
            for e in f["evidence"]
            if e["kind"]
            in {
                "release_asset_inventory",
                "release_artifact",
                "dockerhub_tag_platforms",
                "oci_manifest",
                "oci_image_config",
            }
        ]
        if not cited:
            cited = f["evidence"][:2]
        for e in cited[:4]:
            p = doc.add_paragraph(style="Evidence")
            hyperlink(p, e["kind"].replace("_", " ").capitalize(), e["url"])
            excerpt = e["excerpt"]
            if e["kind"] == "oci_manifest" and e.get("manifest", {}).get("manifests"):
                from .evidence import manifest_platforms

                platforms, complete = manifest_platforms(e["manifest"])
                excerpt = (
                    "Runtime platforms: "
                    + "; ".join(
                        f"{v.get('os') or 'missing'}/{v.get('architecture') or 'missing'}"
                        for v in platforms
                        if not v.get("attestation")
                    )
                    + f". Explicitly labeled attestation descriptors excluded: {sum(bool(v.get('attestation')) for v in platforms)}."
                )
            p.add_run(
                ": "
                + clean(excerpt[:450])
                + ("... [full inventory in JSON]" if len(excerpt) > 450 else "")
            )
        if f["ai_review"]["status"] == "completed":
            doc.add_paragraph("AI advisory review: " + clean(f["ai_review"]["note"]))
            for citation in f["ai_review"]["citations"]:
                p = doc.add_paragraph(style="Evidence")
                hyperlink(p, "Verified review citation", citation["url"])
                p.add_run(": " + clean(citation["quote"]))
        if f["failures"]:
            doc.add_paragraph(
                "Collection issue: " + clean("; ".join(f["failures"])), "Evidence"
            )
    doc.add_heading("Saved investigation history", level=1)
    doc.add_paragraph(
        "SQLite retains candidates, due dates, every completed observation, evidence fingerprints, and run summaries. Repeat runs skip candidates until their refresh date; prior gaps are not presented as newly investigated projects. The table shows each candidate's last saved observation. Rows labeled historical were not rechecked in this run; refer to their original observation dates."
    )
    history = summary["saved_history"]
    if history:
        # Older exported summaries can recover evidence links from their full findings.
        full_findings = {
            f["candidate_id"]: f
            for f in summary["findings"] + summary.get("retained_findings", [])
        }
        historical_ids = {
            f["candidate_id"] for f in summary.get("retained_findings", [])
        }
        t = table(
            doc,
            [
                "Candidate / evidence",
                "Saved status and exact scope",
                "Observed (UTC)",
                "Refresh due (UTC)",
            ],
            [
                [
                    r["candidate_id"],
                    r["status"]
                    + (" (historical)" if r["candidate_id"] in historical_ids else "")
                    + "\n"
                    + r["scope"],
                    r["checked_at"][:16].replace("T", " "),
                    r["next_check_at"][:16].replace("T", " "),
                ]
                for r in history[:30]
            ],
            [2100, 3900, 1680, 1680],
        )
        for row, saved in zip(t.rows[1:], history[:30]):
            url = saved.get("evidence_url")
            if not url:
                evidence = full_findings.get(saved["candidate_id"], {}).get(
                    "evidence", []
                )
                preferred = sorted(
                    evidence,
                    key=lambda e: {
                        "oci_manifest": 0,
                        "release_asset_inventory": 1,
                        "dockerhub_tag_platforms": 2,
                    }.get(e["kind"], 9),
                )
                url = preferred[0]["url"] if preferred else None
            if url:
                p = row.cells[0].add_paragraph(style="Table Text")
                hyperlink(p, "View evidence", url)
            stars = (
                full_findings.get(saved["candidate_id"], {})
                .get("metadata", {})
                .get("stargazers_count")
            )
            if stars is not None:
                row.cells[0].add_paragraph(
                    f"Stars observed: {stars:,}", style="Table Text"
                )
        if len(history) > 30:
            doc.add_paragraph(
                f"Showing 30 of {len(history)} saved candidates; full history is retained in JSON and SQLite.",
                "Evidence",
            )
    doc.add_heading("Boundaries, limits and collection issues", level=1)
    selection = summary.get("selection", {})
    if selection:
        doc.add_paragraph(
            "Selection: "
            + "; ".join(
                f"{s.get('source', 'github')}:{s.get('name', '')}"
                + (":" + s["tag"] if s.get("tag") else "")
                for s in selection["seeds"]
            )
            + ". GitHub discovery queries: "
            + (", ".join(selection["github_queries"]) or "none")
            + f". Minimum search stars: {selection['minimum_stars']}."
        )
    doc.add_paragraph(
        "Configured caps: "
        + "; ".join(
            f"{key.replace('_', ' ')}={value}"
            for key, value in summary["limits"].items()
        )
        + "."
    )
    doc.add_paragraph(
        "Refresh intervals in hours: "
        + "; ".join(f"{key}={value}" for key, value in summary["refresh_hours"].items())
        + "."
    )
    for limitation in summary["limitations"]:
        doc.add_paragraph(limitation)
    if summary["skipped"]:
        doc.add_heading("Skipped or deferred scope", level=2)
        for item in summary["skipped"][:25]:
            doc.add_paragraph(
                clean(
                    (
                        item.get("candidate_id")
                        or item.get("query")
                        or item.get("source")
                        or "Queue"
                    )
                    + ": "
                    + item["reason"]
                ),
                "Evidence",
            )
        if len(summary["skipped"]) > 25:
            doc.add_paragraph(
                "Additional skipped records are retained in JSON.", "Evidence"
            )
    if summary["failures"]:
        doc.add_heading("Collection and review issues", level=2)
        for item in summary["failures"][:25]:
            doc.add_paragraph(
                clean(
                    (item.get("candidate_id") or item.get("source") or "Run")
                    + ": "
                    + item["reason"]
                ),
                "Evidence",
            )
    doc.add_heading("Traceability and artifacts", level=2)
    doc.add_paragraph(
        "The accompanying JSON includes all collected citations, exact scopes, observations, skipped work, collection errors, and report paths. The CSV provides a filterable finding list. State database: "
        + summary["state_path"],
        "Evidence",
    )
    doc.save(paths["docx"])
