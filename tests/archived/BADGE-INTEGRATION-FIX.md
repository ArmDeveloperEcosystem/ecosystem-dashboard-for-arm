# Test Badge Integration Fix

## Problem
The test badge shortcode wasn't displaying on the package pages because:

1. **Site structure**: The ecosystem dashboard doesn't render individual package pages. Instead, it shows all packages in a filterable/searchable table on the homepage.

2. **Template rendering**: The `row-sub.html` partial template (which shows expanded package details) was only displaying specific frontmatter fields, not the `.Content` of the markdown files where the shortcode was placed.

3. **Shortcode location**: The shortcode `{{< test-badge package="nginx" >}}` in `nginx.md` was never being rendered because `.Content` wasn't included in the template.

## Solution
Instead of using a shortcode, we integrated the test badge directly into the `row-sub.html` template that renders the expandedpackage information.

### Changes Made

**File**: `themes/arm-design-system-hugo-theme/layouts/partials/package-display/row-sub.html`

**What was added**: A new section that:
1. Checks if test data exists for the package: `{{ $testData := index $.metadata.Site.Data "test-results" $packageSlug }}`
2. Renders a badge with color coding based on test status
3. Shows test timestamp and version
4. Provides expandable test details
5. Links to the GitHub Actions run

### How It Works

```go-html-template
{{ $packageSlug := .metadata.File.ContentBaseName }}
{{ $testData := index $.metadata.Site.Data "test-results" $packageSlug }}
{{ if $testData }}
  <!-- Render badge section -->
{{ end }}
```

The template:
- Gets the package filename (e.g., "nginx")
- Looks up test data from `data/test-results/nginx.json`
- If test data exists, renders the badge
- Otherwise, shows nothing (graceful degradation)

### Badge Display Features

✅ **Color-coded status**:
- Green (#28a745) for passing tests
- Red (#dc3545) for failing tests
- Gray (#6c757d) for unknown/pending

✅ **Information shown**:
- Test status (e.g., "5 passing")
- Last tested timestamp
- Package version tested
- Link to GitHub Actions run

✅ **Expandable details**:
- Individual test results with emoji indicators
- Test duration for each test
- Total duration
- Runner information (OS and architecture)

## Usage

### Viewing the Badge

1. Start Hugo server: `hugo server -D`
2. Open browser to: **http://localhost:1313/**
3. Search for "nginx" or scroll to find it
4. Click the nginx row to expand it
5. The test badge appears in the expanded section

Alternatively, use the direct link:
**http://localhost:1313/?package=nginx**

### Adding Tests for Other Packages

When you add test workflows for other packages:

1. **Create the workflow**: `.github/workflows/test-<package>.yml`
2. **Run the workflow**: It generates `data/test-results/<package>.json`
3. **Badge appears automatically**: No template changes needed!

The badge will automatically appear for any package that has a corresponding JSON file in `data/test-results/`.

## Files Involved

| File | Purpose |
|------|---------|
| `data/test-results/nginx.json` | Test results data |
| `themes/.../layouts/partials/package-display/row-sub.html` | Renders expanded package info (now includes badge) |
| `themes/.../layouts/shortcodes/test-badge.html` | Shortcode (not used in current implementation) |
| `content/opensource_packages/nginx.md` | Package content (shortcode can be removed) |

## Note on Shortcode

The `test-badge.html` shortcode was created but isn't being used because:
- The site doesn't render `.Content` from package markdown files
- Direct template integration provides better control
- Can still be useful if individual package pages are added later

## Testing

To verify the badge works:

1. **Check data file exists**:
   ```bash
   cat data/test-results/nginx.json | jq
   ```

2. **Start Hugo**:
   ```bash
   hugo server -D
   ```

3. **Open in browser**:
   - Main page: http://localhost:1313/
   - Direct to nginx: http://localhost:1313/?package=nginx

4. **Verify badge shows**:
   - Click nginx row to expand
   - Badge should show "🔧 5 passing" in green
   - Click badge to open GitHub Actions run
   - Expand "View test details" to see individual tests

## Future Enhancements

Possible improvements:
- Add badge to table row (collapsed view) for quick status
- Show test age/freshness indicator
- Add historical test trend
- Support multiple test runs/versions
- Add badge to search results
