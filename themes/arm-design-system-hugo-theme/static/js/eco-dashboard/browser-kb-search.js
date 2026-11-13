/* Optional direct KB transport. Semantic ranking stays in the KB. */
(function () {
    'use strict';

    window.createBrowserKBSearch = function (endpoint, rows) {
        const identities = new Map();
        const slugs = new Set();
        const cache = new Map();
        let invalidCatalog = false;
        for (const row of rows) {
            const id = row.getAttribute('data-catalog-id') || '';
            if (row.id.includes('-placeholder') || row.getAttribute('data-woa') !== 'true' || !id.startsWith('linux/')) continue;
            const slug = row.getAttribute('data-title-urlized');
            const edition = row.getAttribute('data-kb-edition');
            const key = slug + '\0' + edition;
            if (!slug || !['open-source', 'commercial'].includes(edition) || identities.has(key)) invalidCatalog = true;
            identities.set(key, row);
            slugs.add(slug);
        }

        function resolve(hit, edition) {
            if (!hit || hit.doc_type !== 'Ecosystem Dashboard' || hit.platform !== 'linux' ||
                !['open-source', 'commercial'].includes(hit.edition) || (edition && hit.edition !== edition)) {
                throw new Error('Unexpected KB scope');
            }
            const value = hit.url;
            if (typeof value !== 'string' || /[\x00-\x20\x7f-\x9f\\]/.test(value)) throw new Error('Invalid package URL');
            // Check the raw path too: URL() would normalize noncanonical dot paths.
            const parts = value.match(/^https:\/\/(developer\.arm\.com(?::443)?)(\/[^?#]*)(?:\?([^#]*))?$/i);
            if (!parts || !['/ecosystem-dashboard/linux', '/ecosystem-dashboard/linux/'].includes(parts[2])) {
                throw new Error('Noncanonical package URL');
            }
            const packages = new URLSearchParams(parts[3] || '').getAll('package');
            if (packages.length !== 1 || !packages[0] || /[\s\x00-\x1f\x7f-\x9f\\/]/.test(packages[0])) {
                throw new Error('Ambiguous package identity');
            }
            const row = identities.get(packages[0] + '\0' + hit.edition);
            if (!row && slugs.has(packages[0])) throw new Error('KB edition disagrees with catalog');
            return row;
        }

        return async function (query, filters, signal) {
            if (invalidCatalog || typeof query !== 'string' || !query.trim() || query.length > 500) {
                throw new Error('Invalid search request');
            }
            const editions = { all: null, opensource: 'open-source', commercial: 'commercial' };
            if (!Object.hasOwn(editions, filters.license)) throw new Error('Invalid license filter');
            const edition = editions[filters.license];
            const key = JSON.stringify([query, edition]);
            let candidates = cache.get(key);
            if (!candidates || Date.now() - candidates.saved >= 300000) {
                const url = new URL(endpoint);
                if (url.username || url.password || url.hash ||
                    !(url.protocol === 'https:' || (url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)))) {
                    throw new Error('Invalid KB endpoint');
                }
                url.search = new URLSearchParams({ q: query, k: '50', doc_type: 'Ecosystem Dashboard', platform: 'linux' });
                if (edition) url.searchParams.set('edition', edition);
                const response = await fetch(url.href, { method: 'GET', mode: 'cors', credentials: 'omit', redirect: 'error', signal });
                if (!response.ok) throw new Error('KB request failed');
                const data = await response.json();
                if (!data || !Array.isArray(data.results) || data.results.length > 50) throw new Error('Invalid KB results');
                candidates = { saved: Date.now(), rows: [], omitted: false };
                for (const hit of data.results) {
                    const row = resolve(hit, edition);
                    if (row) candidates.rows.push(row);
                    else candidates.omitted = true;
                }
                if (signal.aborted) throw new Error('Search cancelled');
                cache.delete(key);
                cache.set(key, candidates);
                while (cache.size > 128) cache.delete(cache.keys().next().value);
            }
            if (signal.aborted) throw new Error('Search cancelled');
            const results = candidates.rows.filter(row => !filter_card(row) &&
                (!filters.tested_only || row.getAttribute('data-has-arm64-tests') === 'true')).map(row => ({
                id: row.getAttribute('data-catalog-id'),
                reason: (row.getAttribute('data-kb-description') || '').slice(0, 600)
            }));
            const notices = ['Showing up to 50 results ranked by relevance, not every possible match.'];
            if (candidates.omitted) notices.push('Some results are unavailable in this dashboard and were not shown.');
            if (filters.category || filters.tested_only) notices.push('Category and test filters narrow these results; other matching packages may not appear.');
            if (filters.tested_only) notices.push('Recorded Arm64 tests do not mean every test passed. Open a package to see its test results.');
            return { mode: 'kb_scoped', status: results.length ? 'ok' : 'no_matches', results, notices };
        };
    };
}());
