# Deployment Checklist

Use this checklist when deploying the functional testing system.

## Pre-Deployment Checks

- [ ] Review all created files
- [ ] Test nginx workflow manually
- [ ] Verify ARM runners are available in your GitHub organization
- [ ] Ensure repository has proper permissions for workflows

## Files to Review

### GitHub Actions Workflow
- [ ] `.github/workflows/test-nginx.yml` - Main test workflow

### Scripts
- [ ] `build_steps/generate_test_badge.py` - Badge generation utility

### Data Files
- [ ] `data/test-results/nginx.json` - Placeholder test results
- [ ] `data/test-results/README.md` - Schema documentation

### Hugo Theme
- [ ] `themes/arm-design-system-hugo-theme/layouts/shortcodes/test-badge.html` - Badge display shortcode

### Documentation
- [ ] `tests/README.md` - Comprehensive framework documentation
- [ ] `tests/QUICKSTART.md` - Quick start guide
- [ ] `tests/OVERVIEW.md` - System overview

## Testing Steps

### 1. Test the Workflow
```bash
# Commit the workflow file
git add .github/workflows/test-nginx.yml
git commit -m "Add nginx functional test workflow"
git push
```

- [ ] Push workflow to repository
- [ ] Navigate to GitHub Actions tab
- [ ] Manually trigger "Test nginx on ARM64" workflow
- [ ] Wait for completion (should take ~30 seconds)
- [ ] Verify all 5 tests pass
- [ ] Check that JSON artifact is uploaded

### 2. Verify JSON Generation
```bash
# After workflow runs, check the data directory
cat data/test-results/nginx.json
```

- [ ] Verify JSON file is created/updated in `data/test-results/`
- [ ] Check that all fields are populated correctly
- [ ] Verify timestamp is current
- [ ] Confirm badge_status is set correctly

### 3. Test Badge Generation Script
```bash
# Test the Python script
python build_steps/generate_test_badge.py nginx summary
python build_steps/generate_test_badge.py nginx badge
python build_steps/generate_test_badge.py nginx svg
```

- [ ] Script runs without errors
- [ ] Summary displays correctly
- [ ] Badge JSON is valid
- [ ] SVG is generated

### 4. Test Hugo Integration

Add to `content/opensource_packages/nginx.md`:
```markdown
---
name: NGINX
# ... existing frontmatter
---

{{< test-badge package="nginx" >}}

```

- [ ] Add shortcode to nginx.md
- [ ] Build Hugo site locally: `hugo server`
- [ ] Navigate to nginx page
- [ ] Verify badge displays correctly
- [ ] Check that badge links to GitHub Actions run
- [ ] Test expandable details section

### 5. Test Scheduled Runs

- [ ] Wait for scheduled run (2 AM UTC) or
- [ ] Manually trigger workflow daily
- [ ] Verify results update automatically
- [ ] Check git commits from github-actions[bot]

## Configuration Checks

### Workflow Permissions

Ensure the workflow has permission to commit:

```yaml
# Add to workflow if needed
permissions:
  contents: write
```

- [ ] Verify workflow can commit to repository
- [ ] Check that commits include `[skip ci]` tag
- [ ] Confirm commits don't trigger infinite loops

### Branch Protection

If main branch has protection rules:

- [ ] Allow github-actions[bot] to push
- [ ] Configure status checks appropriately
- [ ] Test that workflow can commit results

### Runner Availability

- [ ] Confirm `ubuntu-24.04-arm` runners are available
- [ ] Check runner quotas and limits
- [ ] Verify billing/usage if applicable

## Post-Deployment

### Monitoring

- [ ] Set up notifications for workflow failures
- [ ] Monitor runner usage
- [ ] Track test execution times
- [ ] Review test results regularly

### Documentation

- [ ] Share documentation with team
- [ ] Update main README if needed
- [ ] Add link to tests documentation
- [ ] Document any custom configurations

### Expansion

- [ ] Plan additional packages to test
- [ ] Prioritize packages from `priority_packages.csv`
- [ ] Create workflows for top 5-10 packages
- [ ] Schedule regular review of test coverage

## Rollback Plan

If issues occur:

```bash
# Remove workflow
git rm .github/workflows/test-nginx.yml

# Remove test results
git rm -r data/test-results/

# Remove shortcode usage
# Edit content/opensource_packages/nginx.md to remove {{< test-badge >}}

# Commit and push
git commit -m "Rollback: Remove functional testing"
git push
```

## Success Criteria

- [x] Workflow executes successfully on ARM runner
- [x] All 5 nginx tests pass
- [x] JSON file is generated correctly
- [x] JSON file is committed to repository
- [x] Badge displays on package page
- [x] Badge links to GitHub Actions run
- [x] Scheduled runs work correctly
- [x] Documentation is complete

## Next Steps After Deployment

1. **Add More Package Tests**
   - Copy nginx workflow as template
   - Add tests for top priority packages
   - Focus on diverse package types (Python, Node.js, Go, etc.)

2. **Enhance Badge Display**
   - Add styling to match site theme
   - Create summary page showing all test statuses
   - Add historical trend graphs

3. **Improve Testing**
   - Add performance benchmarks
   - Test multiple versions
   - Compare with x86_64 results

4. **Automate More**
   - Auto-create issues on failures
   - Send notifications to relevant teams
   - Generate weekly test reports

## Contact

For questions or issues:
- Review `tests/README.md`
- Check `tests/QUICKSTART.md`
- See `tests/OVERVIEW.md`
- Review workflow logs in GitHub Actions

## Notes

- Initial workflow created: 2025-11-04
- Based on nginx package testing
- Uses GitHub native ARM runners
- JSON schema version: 1.0
