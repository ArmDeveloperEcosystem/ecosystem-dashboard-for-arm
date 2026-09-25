/* Linux-only enhancement. Existing table rows remain the source of package details. */
(function () {
    'use strict';

    window.createDashboardSearch = function (root) {
        const input = root.querySelector('#nl-search-input');
        const form = root.querySelector('#nl-search-form');
        const submitButton = form.querySelector('button[type="submit"]');
        const tested = root.querySelector('#nl-search-tested');
        const clearButton = root.querySelector('#nl-search-clear');
        const feedback = root.querySelector('#nl-search-feedback');
        const status = root.querySelector('#nl-search-status');
        const interpretation = root.querySelector('#nl-search-interpretation');
        const constraints = root.querySelector('#nl-search-constraints');
        const notice = root.querySelector('#nl-search-notice');
        const refinements = root.querySelector('#nl-search-refinements');
        const state = {
            query: '', context: '', matches: null, fallback: false,
            version: 0, controller: null, filterTimer: null, pending: false
        };

        // Legacy table/filter code expects the ADS search component's async value().
        root.value = () => Promise.resolve(input.value);

        function allRows() {
            return Array.from(document.querySelectorAll('.search-div'));
        }

        function isPlaceholder(row) {
            return row.id.includes('-placeholder');
        }

        function currentFilters() {
            const license = document.querySelector('input.group-license:checked');
            const category = document.querySelector('input.group-category:checked');
            const licenseName = license ? license.getAttribute('data-urlized-name') : 'all';
            const categoryName = category ? category.getAttribute('data-display-name') : 'All';
            return {
                license: licenseName === 'open-source' ? 'opensource' : licenseName,
                category: categoryName === 'All' ? null : categoryName,
                tested_only: tested.checked
            };
        }

        function rowsToHide(rows) {
            const words = sanitizeInput(state.query).toLowerCase().split(/\s+/).filter(Boolean);
            return Array.from(rows).filter(row => {
                if (isPlaceholder(row) || filter_card(row)) return true;
                if (tested.checked && row.getAttribute('data-has-arm64-tests') !== 'true') return true;
                if (state.matches !== null) return !state.matches.has(row.getAttribute('data-catalog-id'));
                if (state.fallback) {
                    const title = (row.getAttribute('data-title') || '').toLowerCase();
                    return !words.every(word => title.includes(word));
                }
                return false;
            });
        }

        function updateCount() {
            const count = allRows().filter(row => !isPlaceholder(row) && !row.hidden).length;
            document.getElementById('currently-shown-number').textContent = String(count);
            const contribute = document.getElementById('if-none-contribute-div');
            contribute.classList.toggle('show', count === 0 && !state.pending);
            contribute.classList.toggle('no-transition', count !== 0 || state.pending);
            return count;
        }

        function renderRows() {
            const rows = allRows();
            hideElements(rows, rowsToHide(rows));
            return updateCount();
        }

        function removeReasons() {
            document.querySelectorAll('.nl-search-match').forEach(node => node.remove());
        }

        function safeEvidenceURL(value) {
            if (typeof value !== 'string' || !value || /[\u0000-\u0020\u007f-\u009f\\]/.test(value)) return null;
            // Require explicit HTTP(S) authority or a local catalog reference;
            // browsers otherwise repair malformed schemes and backslashes.
            const absolute = /^https?:\/\/([^/?#]+)/i.exec(value);
            if (!absolute && !/^(\/(?!\/)|\?)/.test(value)) return null;
            try {
                const page = new URL(window.location.href);
                const url = new URL(value, page);
                if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return null;
                if (absolute) {
                    const authority = absolute[1].toLowerCase();
                    const defaultPort = url.protocol === 'https:' ? ':443' : ':80';
                    if (authority !== url.host && !(url.port === '' && authority === url.host + defaultPort)) return null;
                    // Keep this allowlist aligned with poc.catalog.ARM_HOSTS.
                    const armHosts = ['arm.com', 'www.arm.com', 'developer.arm.com', 'learn.arm.com'];
                    if (url.protocol === 'https:' && !url.port && armHosts.includes(url.hostname)) return url.href;
                }
                const catalogPath = page.pathname.replace(/\/$/, '');
                return url.origin === page.origin && url.pathname.replace(/\/$/, '') === catalogPath && url.searchParams.get('package')
                    ? url.href : null;
            } catch (_) {
                return null;
            }
        }

        function renderReasons() {
            removeReasons();
            for (const row of allRows()) {
                const match = state.matches && state.matches.get(row.getAttribute('data-catalog-id'));
                if (!match) continue;
                const container = document.createElement('div');
                container.className = 'nl-search-match';
                container.textContent = typeof match.reason === 'string' ? match.reason.slice(0, 600) : 'Matches your search in the package catalog.';
                const evidenceURL = safeEvidenceURL(match.evidence_url);
                if (evidenceURL) {
                    const link = document.createElement('a');
                    link.href = evidenceURL;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.textContent = 'View evidence ↗';
                    link.setAttribute('aria-label', 'View evidence for ' + (row.getAttribute('data-title') || 'this package'));
                    link.addEventListener('click', event => event.stopPropagation());
                    container.appendChild(link);
                }
                row.querySelector('.search-title').appendChild(container);
            }
        }

        function renderConstraints() {
            constraints.replaceChildren();
            const filters = currentFilters();
            const labels = ['Linux on Arm'];
            if (filters.license === 'opensource') labels.push('Open source');
            if (filters.license === 'commercial') labels.push('Commercial');
            if (filters.category) labels.push(filters.category);
            if (filters.tested_only) labels.push('Recorded Arm64 tests');
            for (const label of labels) {
                const chip = document.createElement('span');
                chip.textContent = label;
                constraints.appendChild(chip);
            }
        }

        function syncFilters(next) {
            if (!next || typeof next !== 'object') return;
            const desired = {
                license: next.license === 'opensource' ? 'open-source' : next.license,
                category: next.category || 'All'
            };
            for (const group of ['license', 'category']) {
                const options = Array.from(document.querySelectorAll('input.group-' + group));
                const value = String(desired[group] || '').toLowerCase();
                const selected = options.find(option =>
                    option.getAttribute('data-urlized-name').toLowerCase() === value ||
                    option.getAttribute('data-display-name').toLowerCase() === value
                );
                if (!selected) continue;
                options.forEach(option => { option.checked = option === selected; });
                const label = selected.getAttribute('data-display-name');
                const facet = document.getElementById('filter-facet-display-name-group-' + group);
                facet.textContent = (group === 'license' ? 'License: ' : 'Category: ') + label;
                facet.closest('ads-tag').classList.toggle('not-all', label.toLowerCase() !== 'all');
                if (group === 'category' && typeof nameToDescriptionMap !== 'undefined') {
                    const description = document.getElementById('category-description');
                    description.textContent = nameToDescriptionMap[selected.getAttribute('data-urlized-name')] || '';
                }
            }
            if (typeof next.tested_only === 'boolean') tested.checked = next.tested_only;
            updateClearFilterOption();
        }

        function busy(value) {
            state.pending = value;
            root.setAttribute('aria-busy', String(value));
            submitButton.disabled = value;
            submitButton.textContent = value ? 'Searching…' : 'Search →';
        }

        function cancelRequest() {
            state.version += 1;
            if (state.controller) state.controller.abort();
            state.controller = null;
            busy(false);
        }

        function setNotice(message) {
            notice.textContent = message;
            notice.hidden = !message;
        }

        function restoreCatalog() {
            cancelRequest();
            window.clearTimeout(state.filterTimer);
            state.query = '';
            state.context = '';
            state.matches = null;
            state.fallback = false;
            input.value = '';
            clearButton.hidden = true;
            feedback.hidden = !tested.checked;
            interpretation.hidden = true;
            refinements.hidden = true;
            setNotice('');
            removeReasons();
            const count = renderRows();
            status.textContent = tested.checked ? count + ' packages with recorded Arm64 tests.' : '';
            renderConstraints();
        }

        function showNameFallback(query) {
            state.matches = null;
            state.fallback = true;
            state.context = '';
            removeReasons();
            const count = renderRows();
            status.textContent = 'Natural-language search is unavailable. Name search only: ' + count + (count === 1 ? ' match.' : ' matches.');
            interpretation.textContent = 'Package name contains: “' + query + '”';
            interpretation.hidden = false;
            refinements.hidden = true;
            setNotice('Try a package name, such as PostgreSQL, or use the filters. Submit again to retry natural-language search.');
            renderConstraints();
        }

        async function search(query, options) {
            options = options || {};
            query = String(query || '').trim().slice(0, 500);
            input.value = query;
            window.clearTimeout(state.filterTimer);
            if (!query) {
                restoreCatalog();
                return;
            }
            // Unpinning or reapplying the same table search does not make another request.
            if (!options.force && query === state.query && !state.pending) {
                renderRows();
                return;
            }
            const previousQuery = state.context;
            cancelRequest();
            const version = state.version;
            const controller = new AbortController();
            state.controller = controller;
            state.query = query;
            state.matches = new Map();
            state.fallback = false;
            clearButton.hidden = false;
            feedback.hidden = false;
            interpretation.hidden = true;
            refinements.hidden = true;
            setNotice('');
            status.textContent = 'Finding packages for your workload…';
            busy(true);
            removeReasons();
            renderRows();
            renderConstraints();
            const timeout = window.setTimeout(() => controller.abort(), 15000);
            try {
                const payload = { query, filters: currentFilters() };
                if (previousQuery) payload.previous_query = previousQuery;
                if (options.filtersOverride) payload.filters_override = true;
                const response = await fetch(root.dataset.endpoint, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload), signal: controller.signal,
                    credentials: 'same-origin'
                });
                if (!response.ok) throw new Error('Search request failed');
                const data = await response.json();
                if (version !== state.version) return;
                if (!data || !Array.isArray(data.results) || !['ok', 'no_matches'].includes(data.status)) {
                    throw new Error('Search response unavailable');
                }
                const localIDs = new Set(allRows().map(row => row.getAttribute('data-catalog-id')));
                state.matches = new Map();
                let omitted = false;
                for (const result of data.results) {
                    if (result && typeof result.id === 'string' && localIDs.has(result.id)) state.matches.set(result.id, result);
                    else omitted = true;
                }
                state.context = typeof data.interpreted_query === 'string' && data.interpreted_query.trim() ? data.interpreted_query.slice(0, 1800) : query;
                syncFilters(data.constraints);
                busy(false);
                renderReasons();
                const count = renderRows();
                const source = data.mode === 'catalog_fallback' ? 'Catalog search' : 'Search complete';
                status.textContent = count ? source + ' · ' + count + (count === 1 ? ' matching package.' : ' matching packages.') : 'No matching packages in this catalog.';
                interpretation.textContent = 'Interpreted as: ' + state.context;
                interpretation.hidden = false;
                renderConstraints();
                const messages = Array.isArray(data.notices) ? data.notices.filter(item => typeof item === 'string').slice(0, 2).map(item => item.slice(0, 400)) : [];
                if (omitted) messages.push('Suggestions outside the current catalog were omitted.');
                if (!count) messages.push('Try broader wording, adjust the filters, or clear the search to browse all packages.');
                setNotice(messages.join(' '));
                refinements.hidden = count === 0;
            } catch (_) {
                if (version !== state.version) return;
                busy(false);
                showNameFallback(query);
            } finally {
                window.clearTimeout(timeout);
                if (version === state.version) {
                    state.controller = null;
                    busy(false);
                }
            }
        }

        function filtersChanged() {
            window.clearTimeout(state.filterTimer);
            cancelRequest();
            state.filterTimer = window.setTimeout(() => {
                if (input.value.trim()) {
                    // Reuse the full interpreted request after a refinement.
                    const query = input.value.trim() === state.query && state.context ? state.context : input.value;
                    search(query, { force: true, filtersOverride: true });
                } else {
                    restoreCatalog();
                }
            }, 0);
        }

        form.addEventListener('submit', event => {
            event.preventDefault();
            search(input.value, { force: true });
        });
        input.addEventListener('input', () => {
            clearButton.hidden = !input.value;
            if (!input.value.trim()) {
                restoreCatalog();
            } else {
                const wasPending = state.pending;
                cancelRequest();
                window.clearTimeout(state.filterTimer);
                if (wasPending) {
                    state.matches = null;
                    state.query = '';
                    state.fallback = false;
                    removeReasons();
                    renderRows();
                }
                feedback.hidden = false;
                status.textContent = state.query ? 'Search edited. Submit to update the results below.' : 'Press Search to find matching packages.';
                refinements.hidden = true;
                setNotice('');
            }
        });
        clearButton.addEventListener('click', () => { restoreCatalog(); input.focus(); });
        tested.addEventListener('change', filtersChanged);
        root.querySelectorAll('[data-search-example], [data-search-refinement]').forEach(button => {
            button.addEventListener('click', () => {
                search(button.dataset.searchExample || button.dataset.searchRefinement, { force: true });
            });
        });

        return {
            search, rowsToHide, updateCount, filtersChanged,
            resetFilters: () => { tested.checked = false; }
        };
    };
}());
