# NVIDIA Security Bulletin Collector

A SecLens plugin that fetches security bulletins from NVIDIA's official security page.

## Overview

This collector plugin retrieves security bulletins from NVIDIA's product security feed. It collects the 10 most recent bulletins and attempts to get detailed information from either the official NVIDIA GitHub repository or the customer help portal.

## Data Source

- **Homepage**: https://www.nvidia.com/en-us/security/
- **API Endpoint**: https://www.nvidia.com/content/dam/en-zz/Solutions/product-security/product-security.json
- **Alternative Details**: https://nvidia.custhelp.com/

## Features

- Fetches the 10 most recent security bulletins
- Extracts bulletin ID, title, severity, CVE identifiers, and publication dates
- Attempts to retrieve detailed content from NVIDIA's GitHub repository (fallback to customer help portal)
- Implements caching to avoid reprocessing the same bulletins
- Properly parses CVE identifiers and adds them as labels
- Supports time-based filtering and normalization

## Fields Extracted

- **Bulletin ID**: Unique identifier for each bulletin
- **Title**: The title of the security bulletin
- **Severity**: The severity level (Critical, High, Medium, Low)
- **CVE Identifiers**: List of associated CVEs
- **Publication Date**: When the bulletin was published
- **Last Updated**: When the bulletin was last updated

## API Request Headers

The plugin makes requests with appropriate headers to mimic a browser request:

- User-Agent: SecLensNVIDIACollector/1.0
- Accept: application/json, text/javascript, */*; q=0.01
- Various other headers to properly identify the request

## Caching

The plugin implements a caching mechanism using a cursor file (`.nvidia_cursor`) to track already seen bulletin IDs, ensuring only new bulletins are processed on subsequent runs.