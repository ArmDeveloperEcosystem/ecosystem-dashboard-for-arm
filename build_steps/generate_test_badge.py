#!/usr/bin/env python3
"""
Test Results Badge Generator

This script reads test result JSON files and generates badge data
that can be displayed on the ecosystem dashboard.
"""

import json
import os
from datetime import datetime
from pathlib import Path


def load_test_result(package_name):
    """Load test result JSON for a package."""
    test_results_dir = Path(__file__).parent.parent / "data" / "test-results"
    json_file = test_results_dir / f"{package_name}.json"
    
    if not json_file.exists():
        return None
    
    with open(json_file, 'r') as f:
        return json.load(f)


def get_badge_color(status):
    """Get badge color based on test status."""
    colors = {
        "passing": "#4c1",  # green
        "failing": "#e05d44",  # red
        "pending": "#9f9f9f",  # gray
        "unknown": "#9f9f9f"  # gray
    }
    return colors.get(status, colors["unknown"])


def get_badge_data(package_name):
    """Generate badge data for a package."""
    result = load_test_result(package_name)
    
    if not result:
        return {
            "label": "tests",
            "message": "no data",
            "color": get_badge_color("unknown")
        }
    
    badge_status = result.get("metadata", {}).get("badge_status", "unknown")
    passed = result.get("tests", {}).get("passed", 0)
    failed = result.get("tests", {}).get("failed", 0)
    
    if badge_status == "passing":
        message = f"{passed} passing"
    elif badge_status == "failing":
        message = f"{failed} failing"
    else:
        message = badge_status
    
    return {
        "label": "arm64 tests",
        "message": message,
        "color": get_badge_color(badge_status)
    }


def get_test_summary(package_name):
    """Get a human-readable test summary."""
    result = load_test_result(package_name)
    
    if not result:
        return "No test data available"
    
    package = result.get("package", {})
    run = result.get("run", {})
    tests = result.get("tests", {})
    
    timestamp = run.get("timestamp", "unknown")
    if timestamp != "unknown" and timestamp != "pending":
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            timestamp = dt.strftime("%Y-%m-%d %H:%M UTC")
        except:
            pass
    
    summary = f"""
Test Summary for {package.get('name', 'unknown')}
Version: {package.get('version', 'unknown')}
Status: {run.get('status', 'unknown')}
Last Run: {timestamp}
Tests: {tests.get('passed', 0)} passed, {tests.get('failed', 0)} failed, {tests.get('skipped', 0)} skipped
Duration: {tests.get('duration_seconds', 0)}s
Runner: {run.get('runner', {}).get('os', 'unknown')} ({run.get('runner', {}).get('arch', 'unknown')})
Run URL: {run.get('url', 'N/A')}
""".strip()
    
    return summary


def generate_badge_svg(package_name):
    """Generate a simple SVG badge."""
    badge = get_badge_data(package_name)
    
    label = badge["label"]
    message = badge["message"]
    color = badge["color"]
    
    # Simple SVG template (similar to shields.io style)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="150" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="a">
    <rect width="150" height="20" rx="3" fill="#fff"/>
  </mask>
  <g mask="url(#a)">
    <path fill="#555" d="M0 0h75v20H0z"/>
    <path fill="{color}" d="M75 0h75v20H75z"/>
    <path fill="url(#b)" d="M0 0h150v20H0z"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="37.5" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="37.5" y="14">{label}</text>
    <text x="112.5" y="15" fill="#010101" fill-opacity=".3">{message}</text>
    <text x="112.5" y="14">{message}</text>
  </g>
</svg>'''
    
    return svg


def main():
    """Main function for CLI usage."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python generate_test_badge.py <package_name> [command]")
        print("Commands: badge, summary, svg")
        print("Example: python generate_test_badge.py nginx summary")
        sys.exit(1)
    
    package_name = sys.argv[1]
    command = sys.argv[2] if len(sys.argv) > 2 else "summary"
    
    if command == "badge":
        badge = get_badge_data(package_name)
        print(json.dumps(badge, indent=2))
    elif command == "summary":
        print(get_test_summary(package_name))
    elif command == "svg":
        print(generate_badge_svg(package_name))
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
