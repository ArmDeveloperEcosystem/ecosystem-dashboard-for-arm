'use strict';
const byId = id => document.getElementById(id);
const labels = { supported: 'Arm64 supported', gap: 'Support gap identified', unknown: 'Unclear / unknown' };
let state = {}, lastRun = null;
function displayText(value) { return String(value).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ud800-\udfff\ufffe\uffff]/gu, char => '\\u' + char.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')); }
function node(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = displayText(text); if (cls) e.className = cls; return e; }
function date(value) { if (!value) return 'not available'; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString(); }
function safeLink(url) { try { if (/[\s\\\u0000-\u001f\ud800-\udfff\ufffe\uffff]/u.test(url)) return false; const u = new URL(url); return u.protocol === 'https:' && !u.username && !u.password && (!u.port || u.port === '443') && ['github.com','api.github.com','hub.docker.com','registry-1.docker.io','auth.docker.io'].includes(u.hostname); } catch { return false; } }
function list(id, values, describe) { const list = byId(id); list.replaceChildren(); for (const item of values) list.append(node('li', describe(item))); }
function renderFindings(summary) {
  const parent = byId('findings'); parent.replaceChildren();
  const filter = byId('filter').value;
  const rows = [...(summary.findings || []), ...(summary.retained_findings || [])].filter(f => filter === 'all' || (filter === 'coverage' ? f.assessment_coverage?.review_required === true : f.status === filter));
  const priority = {gap:0, unknown:1, supported:2}; rows.sort((a,b) => priority[a.status] - priority[b.status]);
  if (!rows.length) { parent.append(node('p', 'No findings in this view. Previously checked findings remain in saved history.', 'empty')); return; }
  for (const f of rows) {
    const card = node('article', undefined, 'finding');
    const top = node('div', undefined, 'finding-top'); const title = node('div'); title.append(node('h3', f.name), node('p', f.source === 'github' ? 'Project repository' : 'Container registry', 'source'));
    top.append(title, node('span', labels[f.status] || 'Unknown', `badge ${f.status}`)); card.append(top);
    card.append(node('p', f.scope, 'scope'), node('p', f.reason, 'reason'));
    const facts = node('div', undefined, 'facts');
    facts.append(node('span', `${f.historical ? 'Historical · last checked' : 'Checked'} ${date(f.checked_at)}`, f.historical ? 'history' : ''), node('span', `Next check: ${date(f.next_check_at)}`), node('span', `Catalog URL match: ${f.catalog_tracked === true ? 'yes' : f.catalog_tracked === false ? 'none found' : 'not available'}`), node('span', f.investigated_before ? 'Existing investigation refreshed' : 'First investigation'));
    card.append(facts, node('p', `Why selected: ${f.selection_reason || 'Selected investigation scope'}`, 'selection'));
    for (const signal of f.popularity_signals || []) card.append(node('p', `${signal.name}: ${signal.value == null ? 'unavailable' : Number(signal.value).toLocaleString()} · ${signal.period || 'period not supplied'} · observed ${date(signal.observed_at)}`, 'selection'));
    card.append(node('p', f.recommended_action, 'action'));
    renderCoverage(card, f);
    const details = node('details'); details.append(node('summary', `Evidence and interpretation (${(f.evidence || []).length} sources)`)); const sources = node('ul', undefined, 'evidence');
    for (const e of f.evidence || []) { const li = node('li'); if (safeLink(e.url)) { const a = node('a', e.kind.replaceAll('_',' ')); a.href = e.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; li.append(a); } else li.append(node('span', `${e.kind} · source link unavailable`)); li.append(node('small', e.excerpt)); sources.append(li); }
    details.append(sources);
    const ai = f.ai_review || {}; details.append(node('p', ai.status === 'completed' ? `AI advisory: ${ai.note}` : `AI interpretation: ${(ai.status || 'not configured').replaceAll('_',' ')}${ai.reason ? '. '+ai.reason : ''}`, 'selection'));
    for (const error of f.failures || []) details.append(node('p', `Collection issue: ${error}`, 'selection'));
    card.append(details); parent.append(card);
  }
}
function renderCoverage(card, finding) {
  const coverage = finding.assessment_coverage;
  if (!coverage) {
    card.append(node('p', finding.source === 'github' ? 'Structured inventory coverage was not recorded for this finding. See its dated scope and evidence.' : 'Assessment covers the exact container tag and platform metadata described above.', 'selection'));
    return;
  }
  if (coverage.review_required) {
    card.append(node('p', 'Coverage review needed: ' + (coverage.review_reasons || []).join(' '), 'coverage-warning'));
  }
  const details = node('details', undefined, 'coverage');
  details.append(node('summary', 'Assessment coverage and bounded inventory'));
  details.append(node('p', `Inventory completeness: ${coverage.inventory_complete === true ? 'complete for the inspected scope' : coverage.inventory_complete === false ? 'incomplete' : 'not established'}. Coverage review does not change the support verdict.`, 'selection'));
  const assessed = coverage.supported_artifacts || [];
  details.append(node('p', assessed.length ? 'Verified advertised Linux Arm64 artifacts: ' + assessed.join('; ') : 'No advertised Linux Arm64 artifact was established in this inventory.', 'selection'));
  const inventory = coverage.remaining_inventory || [];
  details.append(node('p', `Remaining collected inventory (${inventory.length}): architecture companions and other components are not automatically classified as gaps.`, 'selection'));
  const rows = node('ul', undefined, 'inventory');
  for (const item of inventory) rows.append(node('li', `${item.name || '(unnamed asset)'} · ${(item.assessment || 'unassessed').replaceAll('_', ' ')}${item.reason ? ': ' + item.reason : ''}`));
  details.append(rows);
  for (const url of coverage.evidence_urls || []) {
    const p = node('p', undefined, 'selection');
    if (safeLink(url)) { const a = node('a', 'Inventory evidence'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); }
    else p.append(node('span', 'Inventory evidence (non-clickable): ' + url));
    details.append(p);
  }
  card.append(details);
}
function activityText(summary) {
  if (summary?.scheduling?.status === 'no_progress') return 'Run needs attention: due investigations could not start within the resource budget. Saved work is retained.';
  if (summary?.outcome === 'degraded') return 'Run finished with issues. Review incomplete evidence and run diagnostics.';
  return 'Run complete. Findings await human review.';
}
function render(summary) {
  if (!summary) return;
  for (const key of ['investigated','supported','gap','unknown']) byId(key).textContent = summary.counts[key] ?? 0;
  byId('run-meta').textContent = `Report ${summary.run_id} · ${date(summary.generated_at)} · ${summary.counts.newly_investigated} new / ${summary.counts.refreshed} refreshed`;
  byId('budget').textContent = `This run: ${summary.counts.requests} metadata requests. Limits: ${summary.limits.max_candidates} investigations, ${summary.limits.max_requests} requests, ${summary.limits.max_seconds}s collection budget.`;
  byId('ai-state').textContent = summary.ai_review.disclosure;
  const selection = summary.selection || {};
  byId('source-counts').textContent = selection.source_records_fetched == null ? 'Detailed collection counts were not recorded for this saved run.' : `Discovery: ${selection.source_records_fetched} source records collected; ${selection.source_records_examined ?? 0} examined; ${selection.source_candidates_selected ?? 0} candidates selected.`;
  const scheduling = summary.scheduling;
  byId('scheduling').textContent = scheduling ? `Queue progress: ${scheduling.attempted} attempted; ${scheduling.deferred_due} due scopes deferred. ${scheduling.reason || ''}` : 'Queue progress details were not recorded for this saved run.';
  byId('memory').textContent = `${(summary.retained_findings || []).length} historical findings retained; ${(summary.queue || []).length} candidates waiting for first investigation. ${summary.counts.saved_observations} observations saved across runs. ${(summary.quarantined_candidates || []).length} saved identities require manual review.`;
  for (const id of ['word','csv','json']) byId(id).hidden = false;
  list('queue', summary.queue || [], q => `${q.name} · saved for a later run`);
  list('quarantined', summary.quarantined_candidates || [], q => `${q.candidate_id}: ${q.reason}`);
  list('skipped', summary.skipped || [], s => `${s.candidate_id || s.candidate || s.source || 'Selection'}: ${s.reason}${s.count != null ? ` (${s.count})` : ''}`);
  list('failures', summary.failures || [], f => `${f.candidate_id || f.source}: ${f.reason}`);
  if (!(summary.failures || []).length) byId('failures').append(node('li', 'No collection issues recorded in this run.'));
  renderFindings(summary);
}
async function refresh() {
  try {
    const response = await fetch('/api/state'); if (!response.ok) throw new Error(`HTTP ${response.status}`); state = await response.json();
    byId('run').disabled = state.running;
    byId('activity').textContent = state.running ? 'Collecting evidence within the configured limits. The previous report remains available.' : state.error ? `Run failed: ${state.error}. The last completed report is retained.` : state.summary ? activityText(state.summary) : 'Ready. Run discovery to collect public repository and registry evidence.';
    if (state.summary && lastRun !== state.summary.run_id) { lastRun = state.summary.run_id; render(state.summary); }
  } catch (error) { byId('activity').textContent = `Local runner unavailable: ${error.message}`; byId('run').disabled = true; }
}
byId('filter').addEventListener('change', () => { if (state.summary) renderFindings(state.summary); });
byId('run').addEventListener('click', async () => {
  byId('run').disabled = true;
  try { const r = await fetch('/api/run', {method:'POST', headers:{'X-CSRF-Token':state.csrf_token}}); if (!r.ok) throw new Error((await r.json()).error); await refresh(); } catch (error) { byId('activity').textContent = error.message; byId('run').disabled = false; }
});
refresh(); setInterval(refresh, 2000);
