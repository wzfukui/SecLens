# Atlassian Security Advisories Collector

This plugin collects security advisories and vulnerability information from Atlassian's public vulnerability transparency API.

## Overview

The Atlassian Security Advisories Collector fetches the latest security information from Atlassian's official vulnerability database. It retrieves CVE details, affected products, severity ratings, and additional information from tracking URLs. The plugin focuses on recent vulnerabilities (published within the last 10 days) and provides detailed information for security teams.

## Data Sources

- **Primary API**: `https://www.atlassian.com/gateway/api/vuln-transparency/v1/products`
- **Tracking URLs**: JIRA issue pages for additional details
- **Official Portal**: `https://www.atlassian.com/trust/data-protection/vulnerabilities`

## Features

- Fetches real-time vulnerability data from Atlassian's official API
- Extracts CVE details including summaries, descriptions, and severity ratings
- Identifies affected products and versions
- Optionally fetches additional details from JIRA tracking URLs
- Filters for recent vulnerabilities (last 10 days)
- Categorizes entries under the `vendor_updates` group

## Information Collected

For each vulnerability, the plugin collects:

- **CVE ID**: The unique CVE identifier
- **Title/Summary**: Brief description of the vulnerability
- **Description**: Detailed information about the vulnerability
- **Publish Date**: When the vulnerability was published
- **Severity**: CVSS score or severity rating
- **Affected Products**: List of Atlassian products and versions affected
- **Tracking URL**: Link to the original JIRA issue (if available)

## Technical Details

- **Collection Frequency**: Every hour (3600 seconds)
- **Timezone**: UTC
- **Data Filtering**: Recent vulnerabilities only (last 10 days)
- **Fallback Mechanism**: If detailed tracking page is unavailable, uses primary API data

## Requirements

- Python 3.8+
- `requests` library
- `beautifulsoup4` library
- FastAPI-based SecLens platform

## Installation

1. Package the plugin using the SecLens packaging script:
   ```bash
   python scripts/package_plugins.py --resources-dir plugins/atlassian_security
   ```

2. Upload the plugin to your SecLens instance:
   ```bash
   python scripts/upload_plugin.py dist/plugins/atlassian_security-1.0.0.zip
   ```

3. Activate the plugin through the SecLens admin interface.

## Error Handling

The plugin implements robust error handling:

- API request timeouts and retries
- JSON parsing validation
- HTML parsing fallbacks
- Individual CVE processing (continues if one fails)

## Security Considerations

- No credentials required - uses public API
- Implements rate limiting to respect Atlassian's terms
- Validates and sanitizes all external data
- Only processes trusted sources