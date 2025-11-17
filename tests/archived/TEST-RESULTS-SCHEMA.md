# Test Results

This directory contains automated test results for packages in the ecosystem dashboard.

## Structure

Each package has its own JSON file (e.g., `nginx.json`) that contains:
- Package metadata (name, version, category)
- Test run information (timestamp, status, runner details)
- Test results (passed/failed counts, duration)
- Dashboard integration metadata

## JSON Schema

```json
{
  "schema_version": "1.0",
  "package": {
    "name": "string",
    "version": "string",
    "language": "string",
    "category": "string"
  },
  "run": {
    "id": "string",
    "url": "string",
    "timestamp": "ISO 8601 timestamp",
    "status": "success|failure",
    "runner": {
      "os": "string",
      "arch": "string"
    }
  },
  "tests": {
    "passed": "number",
    "failed": "number",
    "skipped": "number",
    "duration_seconds": "number",
    "details": [
      {
        "name": "string",
        "status": "passed|failed|skipped",
        "duration_seconds": "number"
      }
    ]
  },
  "metadata": {
    "dashboard_link": "string",
    "badge_status": "passing|failing"
  }
}
```

## Usage

These JSON files are generated automatically by GitHub Actions workflows and can be used to:
- Display test badges on package pages
- Show the latest test status
- Link to detailed test runs
- Track package health over time

## Automated Updates

Test results are updated automatically:
- Daily via scheduled workflow runs
- On package content changes
- On workflow configuration changes
- Can be triggered manually
