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
        const notice = root.querySelector('#nl-search-notice');
        const details = root.querySelector('#nl-search-details');
        const detailsCopy = root.querySelector('#nl-search-details-copy');
        const refinements = root.querySelector('#nl-search-refinements');
        const examples = root.querySelector('#nl-search-examples');
        const state = {
            query: '', matches: null, fallback: false,
            version: 0, controller: null, filterTimer: null, pending: false
        };

        const browseOrder = new Map(allRows().map((row, index) => [row.getAttribute('data-catalog-id'), index]));
        const browserSearch = root.dataset.transport === 'browser' ? window.createBrowserKBSearch(root.dataset.endpoint, allRows()) : null;

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
                if (isPlaceholder(row)) return true;
                if (state.matches !== null) return !state.matches.has(row.getAttribute('data-catalog-id'));
                if (filter_card(row)) return true;
                if (tested.checked && row.getAttribute('data-has-arm64-tests') !== 'true') return true;
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
            document.getElementById('results-status-bar').hidden = Boolean(state.query || tested.checked);
            const contribute = document.getElementById('if-none-contribute-div');
            contribute.classList.toggle('show', count === 0 && !state.pending);
            contribute.classList.toggle('no-transition', count !== 0 || state.pending);
            return count;
        }

        function orderRows() {
            const rank = new Map(state.matches ? Array.from(state.matches.keys(), (id, index) => [id, index]) : []);
            const tables = new Map();
            // Capture adjacent details before moving anything. Pinned placeholders
            // share the package ID, so unpinning can restore the existing row pair.
            for (const row of allRows()) {
                const table = row.parentNode;
                if (!table) continue;
                if (!tables.has(table)) tables.set(table, []);
                tables.get(table).push({ row, details: row.nextElementSibling });
            }
            for (const [table, pairs] of tables) {
                const firstRow = pairs[0].row;
                const lastPair = pairs[pairs.length - 1];
                const afterRows = (lastPair.details || lastPair.row).nextElementSibling;
                const searching = state.matches !== null;
                const ordered = searching ? pairs.filter(({ row }) =>
                    row.classList.contains('js-pinned') || rank.has(row.getAttribute('data-catalog-id'))
                ) : pairs;
                ordered.sort((a, b) => {
                    const aPinned = a.row.classList.contains('js-pinned');
                    const bPinned = b.row.classList.contains('js-pinned');
                    if (aPinned !== bPinned) return aPinned ? -1 : 1;
                    if (aPinned) return 0; // Preserve the user's pinned section.
                    const aID = a.row.getAttribute('data-catalog-id');
                    const bID = b.row.getAttribute('data-catalog-id');
                    return (rank.get(aID) ?? Infinity) - (rank.get(bID) ?? Infinity) ||
                        (browseOrder.get(aID) ?? Infinity) - (browseOrder.get(bID) ?? Infinity);
                });
                // Promote only result/pinned pairs; hidden rows need no reordering.
                // Restore browse order from the end so promoted pairs move back
                // without reconnecting every intervening row's custom elements.
                if (!searching) ordered.reverse();
                let cursor = searching ? firstRow : afterRows;
                for (const { row, details } of ordered) {
                    const inPlace = searching ? row === cursor : (details || row).nextElementSibling === cursor;
                    if (!inPlace) {
                        table.insertBefore(row, cursor);
                        if (details) table.insertBefore(details, cursor);
                    }
                    cursor = searching ? (details || row).nextElementSibling : row;
                }
            }
        }

        function renderRows() {
            if (!state.pending) orderRows();
            const rows = allRows();
            hideElements(rows, rowsToHide(rows));
            return updateCount();
        }

        function removeReasons() {
            document.querySelectorAll('.nl-search-match').forEach(node => node.remove());
        }

        function renderReasons() {
            removeReasons();
            for (const row of allRows()) {
                const match = state.matches && state.matches.get(row.getAttribute('data-catalog-id'));
                if (!match || isPlaceholder(row)) continue;
                const container = document.createElement('div');
                container.className = 'nl-search-match';
                container.textContent = typeof match.reason === 'string' ? match.reason.slice(0, 600) : 'Open this package to view its details.';
                row.querySelector('.search-title').appendChild(container);
            }
        }

        function syncFilters(next) {
            if (!next || typeof next !== 'object') return;
            const options = Array.from(document.querySelectorAll('input.group-license'));
            const value = String(next.license === 'opensource' ? 'open-source' : next.license || '').toLowerCase();
            const selected = options.find(option =>
                option.getAttribute('data-urlized-name').toLowerCase() === value ||
                option.getAttribute('data-display-name').toLowerCase() === value
            );
            if (selected) {
                options.forEach(option => { option.checked = option === selected; });
                const label = selected.getAttribute('data-display-name');
                const facet = document.getElementById('filter-facet-display-name-group-license');
                facet.textContent = 'License: ' + label;
                facet.closest('ads-tag').classList.toggle('not-all', label.toLowerCase() !== 'all');
            }
            if (typeof next.tested_only === 'boolean') tested.checked = next.tested_only;
            updateClearFilterOption();
        }

        function busy(value) {
            state.pending = value;
            root.setAttribute('aria-busy', String(value));
            submitButton.disabled = value;
            submitButton.textContent = value ? 'Searching…' : 'Search';
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

        function resetDetails() {
            details.hidden = true;
            details.open = false;
            detailsCopy.textContent = '';
        }

        function restoreCatalog() {
            cancelRequest();
            window.clearTimeout(state.filterTimer);
            state.query = '';
            state.matches = null;
            state.fallback = false;
            input.value = '';
            clearButton.hidden = true;
            examples.hidden = false;
            feedback.hidden = !tested.checked;
            resetDetails();
            refinements.hidden = true;
            setNotice('');
            removeReasons();
            const count = renderRows();
            status.textContent = tested.checked ? count + ' packages with recorded Arm64 tests.' : '';
        }

        function showNameFallback() {
            state.matches = null;
            state.fallback = true;
            removeReasons();
            const count = renderRows();
            status.textContent = 'Natural-language search is unavailable. Name search only: ' + count + (count === 1 ? ' match.' : ' matches.');
            resetDetails();
            refinements.hidden = true;
            setNotice('Try a package name or use the filters. Clear search to browse all packages, or submit again to retry.');
        }

        async function search(query, options) {
            options = options || {};
            query = String(query || '');
            input.value = query;
            window.clearTimeout(state.filterTimer);
            if (!query.trim()) {
                restoreCatalog();
                return;
            }
            // Unpinning or reapplying the same table search does not make another request.
            if (!options.force && query === state.query && !state.pending) {
                renderReasons();
                renderRows();
                return;
            }
            cancelRequest();
            const version = state.version;
            const controller = new AbortController();
            state.controller = controller;
            state.query = query;
            state.matches = new Map();
            state.fallback = false;
            clearButton.hidden = false;
            examples.hidden = true;
            feedback.hidden = false;
            resetDetails();
            refinements.hidden = true;
            setNotice('');
            status.textContent = 'Finding packages for your workload…';
            busy(true);
            removeReasons();
            renderRows();
            const timeout = window.setTimeout(() => controller.abort(), 15000);
            try {
                let data;
                if (browserSearch) {
                    data = await browserSearch(query, currentFilters(), controller.signal);
                } else {
                    const payload = { query, filters: currentFilters() };
                    const response = await fetch(root.dataset.endpoint, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload), signal: controller.signal,
                        credentials: 'same-origin'
                    });
                    if (!response.ok) throw new Error('Search request failed');
                    data = await response.json();
                }
                if (version !== state.version) return;
                if (!data || data.mode !== 'kb_scoped' || !Array.isArray(data.results) || !['ok', 'no_matches'].includes(data.status)) {
                    throw new Error('Search response unavailable');
                }
                const localIDs = new Set(allRows().filter(row => !isPlaceholder(row)).map(row => row.getAttribute('data-catalog-id')));
                state.matches = new Map();
                let omitted = false;
                for (const result of data.results) {
                    if (result && typeof result.id === 'string' && localIDs.has(result.id)) {
                        state.matches.set(result.id, result);
                    } else omitted = true;
                }
                busy(false);
                renderReasons();
                const count = renderRows();
                status.textContent = count ? count + (count === 1 ? ' result' : ' results') : 'No matches found.';
                const messages = Array.isArray(data.notices) ? data.notices.filter(item => typeof item === 'string').slice(0, 5).map(item => item.slice(0, 400)) : [];
                const explanations = ['Packages are ranked by the Arm Knowledge Base.'];
                const warnings = [];
                // Fold only known explanatory notices; unexpected messages stay visible.
                const routinePrefixes = ['Showing up to', 'Category and test filters',
                    'Recorded Arm64 tests', 'No matching current catalog packages were found'];
                for (const message of messages) {
                    (routinePrefixes.some(prefix => message.startsWith(prefix)) ? explanations : warnings).push(message);
                }
                if (allRows().some(row => !row.hidden && !isPlaceholder(row) && row.classList.contains('js-pinned'))) explanations.push('Pinned packages stay at the top.');
                if (omitted) warnings.push('Some results are unavailable in this dashboard and were not shown.');
                if (!count) warnings.push('Try broader wording, adjust the filters, or clear the search to browse all packages.');
                setNotice(warnings.join(' '));
                detailsCopy.textContent = explanations.join(' ');
                details.hidden = false;
                refinements.hidden = count === 0 || currentFilters().license === 'opensource';
                examples.hidden = count > 0;
            } catch (_) {
                if (version !== state.version) return;
                busy(false);
                showNameFallback();
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
                    search(input.value, { force: true });
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
                    examples.hidden = false;
                    removeReasons();
                    renderRows();
                }
                feedback.hidden = false;
                status.textContent = state.query ? 'Search edited. Submit to update the results below.' : 'Press Search to find matching packages.';
                refinements.hidden = true;
                resetDetails();
                setNotice('');
            }
        });
        clearButton.addEventListener('click', () => { restoreCatalog(); input.focus(); });
        tested.addEventListener('change', filtersChanged);
        root.querySelectorAll('[data-search-example], [data-search-refinement]').forEach(button => {
            button.addEventListener('click', () => {
                input.focus();
                if (button.dataset.searchExample) {
                    search(button.dataset.searchExample, { force: true });
                    return;
                }
                const filters = currentFilters();
                if (button.dataset.searchRefinement === 'opensource') filters.license = 'opensource';
                syncFilters(filters);
                search(state.query, { force: true });
            });
        });

        return {
            search, rowsToHide, updateCount, filtersChanged,
            resetFilters: () => { tested.checked = false; }
        };
    };
}());
