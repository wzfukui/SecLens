"""Atlassian Security Advisories Collector

This module collects vulnerability information from Atlassian's public API
and optionally fetches additional details from their JIRA issue tracking system.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

from app.schemas import BulletinCreate, SourceInfo, ContentInfo


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_cve_details_from_json(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract CVE details from the main JSON response."""
    cve_list = []
    cve_metadata = json_data.get('cve_metadata', {})
    
    # Initialize a mapping of CVEs to products first
    cve_to_products = {}
    
    # Process products to map CVEs to affected products
    all_products = json_data.get('products', {})
    for product_name, product_info in all_products.items():
        for version, cve_list_for_version in product_info.get('versions', {}).items():
            for cve_item in cve_list_for_version:
                if isinstance(cve_item, dict):
                    for item_cve_id, status in cve_item.items():
                        if item_cve_id not in cve_to_products:
                            cve_to_products[item_cve_id] = []
                        cve_to_products[item_cve_id].append({
                            'product': product_name,
                            'version': version,
                            'status': status
                        })
    
    # Process each CVE in metadata
    for cve_id, cve_info in cve_metadata.items():
        if not cve_info:
            continue
            
        cve_details = {
            'cve_id': cve_id,
            'summary': cve_info.get('cve_summary', ''),
            'description': cve_info.get('cve_description', ''),
            'publish_date': parse_atlassian_date(cve_info.get('cve_publish_date', '')),
            'severity': cve_info.get('cve_severity', ''),
            'tracking_url': cve_info.get('atl_tracking_url', ''),
            'affected_products': cve_to_products.get(cve_id, [])
        }
        cve_list.append(cve_details)
    
    return cve_list


def parse_atlassian_date(date_str: str) -> Optional[datetime]:
    """Parse Atlassian date string to datetime object."""
    if not date_str:
        return None
    try:
        # Format: "2023-11-21T18:03:05.000+0000"
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        try:
            # Handle the specific format from Atlassian
            return datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.000+0000')
        except ValueError:
            logger.warning(f"Could not parse date: {date_str}")
            return None


def fetch_additional_details_from_jira(url: str) -> Optional[str]:
    """Fetch additional details from JIRA issue page."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Try to get content from details-module first
        details_module = soup.find('div', id='details-module')
        if details_module:
            # Extract text content from the details module
            text_content = details_module.get_text(separator=' ', strip=True)
            return clean_html_content(text_content)
        
        # Fallback to issue-container if details-module is not found
        issue_container = soup.find('div', class_='issue-container')
        if issue_container:
            # Extract text content from the issue container
            text_content = issue_container.get_text(separator=' ', strip=True)
            return clean_html_content(text_content)
        
        logger.warning(f"No details-module or issue-container found in JIRA page: {url}")
        return None

    except Exception as e:
        logger.warning(f"Failed to fetch additional details from JIRA {url}: {str(e)}")
        return None


def clean_html_content(content: str) -> str:
    """Clean HTML content by removing extra whitespace and formatting."""
    if not content:
        return content
    
    # Remove extra whitespace and newlines
    cleaned = re.sub(r'\s+', ' ', content)
    return cleaned.strip()


def filter_recent_cves(cve_list: List[Dict[str, Any]], days: int = 30) -> List[Dict[str, Any]]:
    """Filter CVEs that were published within the last 'days' days."""
    from datetime import timezone
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    recent_cves = []
    
    for cve in cve_list:
        publish_date = cve.get('publish_date')
        if publish_date:
            # Convert to timezone-aware if it's naive and assume UTC
            if publish_date.tzinfo is None:
                publish_date = publish_date.replace(tzinfo=timezone.utc)
            if publish_date >= cutoff_date:
                recent_cves.append(cve)
    
    return recent_cves


def create_bulletin_from_cve(cve_info: Dict[str, Any]) -> BulletinCreate:
    """Create a BulletinCreate object from CVE information."""
    # Create the main content description
    description = cve_info.get('description', '')
    
    # Fetch additional details from JIRA if available
    tracking_url = cve_info.get('tracking_url', '')
    if tracking_url:
        additional_details = fetch_additional_details_from_jira(tracking_url)
        if additional_details:
            # Append additional details to description
            description += f"\n\nAdditional details from tracking URL: {additional_details}"
    
    # Format affected products information
    affected_products = cve_info.get('affected_products', [])
    if affected_products:
        product_info = "\nAffected products:\n"
        for product in affected_products:
            product_info += f"- {product.get('product', '')} version {product.get('version', '')} ({product.get('status', '')})\n"
        description += product_info
    
    # Verify we have required fields to avoid creating invalid entries
    cve_id = cve_info.get('cve_id')
    if not cve_id:
        raise ValueError("Missing CVE ID - cannot create bulletin without valid identifier")
    
    # Ensure we have a valid title
    title = cve_info.get('summary', '').strip()
    if not title:
        title = cve_id  # Use CVE ID as title if summary is empty
    
    return BulletinCreate(
        source=SourceInfo(
            source_slug="atlassian_security",
            external_id=cve_id,
            origin_url=tracking_url or None
        ),
        content=ContentInfo(
            title=title,
            summary=title,  # Use the same title for summary if needed
            body_text=description,
            published_at=cve_info.get('publish_date'),
            language="en"
        ),
        severity=str(cve_info.get('severity', '')),
        labels=["atlassian", "security", "cve"] + [p['product'].replace(" ", "_").lower() for p in affected_products if p.get('product')],
        extra={
            "cve_id": cve_id,
            "tracking_url": tracking_url,
            "affected_products": affected_products
        },
        raw=cve_info
    )


def fetch_atlassian_security_data() -> Dict[str, Any]:
    """Fetch security data from Atlassian's API."""
    url = "https://www.atlassian.com/gateway/api/vuln-transparency/v1/products"
    
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'cache-control': 'no-cache',
        'dnt': '1',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://sec-vuln-transparency-ui.prod-east.frontend.public.atl-paas.net/',
        'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross-site',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    }
    
    # Try multiple times with delays in case of network issues
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Attempt {attempt + 1} failed to fetch data from Atlassian API: {str(e)}")
            if attempt == max_retries - 1:  # Last attempt
                logger.error(f"Failed to fetch data from Atlassian API after {max_retries} attempts")
                return {}
        except ValueError as e:  # JSON decode error
            logger.error(f"Failed to parse JSON response from Atlassian API: {str(e)}")
            return {}


def run(
    ingest_url: Optional[str] = None,
    token: Optional[str] = None,
    **kwargs,
) -> tuple[List[BulletinCreate], Optional[Dict[str, Any]]]:
    """Main function to run the Atlassian security collector."""
    logger.info("Starting Atlassian security advisories collection...")
    
    try:
        # Fetch data from Atlassian API
        json_data = fetch_atlassian_security_data()
        if not json_data:
            logger.error("No data received from Atlassian API")
            return [], None
        
        # Extract CVE details from JSON
        cve_list = extract_cve_details_from_json(json_data)
        logger.info(f"Extracted {len(cve_list)} CVE entries from JSON")
        
        # Filter for recent CVEs (last 30 days)
        recent_cves = filter_recent_cves(cve_list, days=30)  # Changed from 10 to 30 days
        logger.info(f"Filtered to {len(recent_cves)} recent CVEs (last 30 days)")
        
        # Create bulletins from recent CVEs
        bulletins = []
        for cve_info in recent_cves:
            try:
                bulletin = create_bulletin_from_cve(cve_info)
                bulletins.append(bulletin)
            except Exception as e:
                logger.error(f"Error creating bulletin for CVE {cve_info.get('cve_id', 'Unknown')}: {str(e)}")
                continue  # Continue with next CVE instead of failing the entire collection
        
        logger.info(f"Created {len(bulletins)} bulletins for ingestion")
        
        # Submit bulletins to the ingestion endpoint if URL and token are provided
        response_data = None
        if ingest_url and bulletins:
            # Check if the URL is not a placeholder
            if ingest_url == "https://host/v1/ingest/bulletins":
                logger.warning("Using placeholder ingest_url, actual ingestion will be skipped")
            else:
                import json
                import requests
                
                logger.info(f"Attempting to submit {len(bulletins)} bulletins to {ingest_url}")
                
                session = requests.Session()
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                session.headers.update(headers)
                
                # Convert bulletins to JSON-serializable format
                payload = [b.model_dump(mode="json") for b in bulletins]
                response = session.post(ingest_url, json=payload, timeout=30)
                response.raise_for_status()
                
                try:
                    response_data = response.json()
                    logger.info(f"Successfully submitted {len(bulletins)} bulletins to ingestion endpoint: {response_data}")
                except json.JSONDecodeError:
                    response_data = {"status_code": response.status_code}
                    logger.info(f"Successfully submitted {len(bulletins)} bulletins, response not JSON: {response.status_code}")
        else:
            logger.warning(
                "Skipping data submission. ingest_url_provided=%s token_provided=%s bulletins=%d",
                bool(ingest_url),
                bool(token),
                len(bulletins),
            )
        
        # Return bulletins and response data
        return bulletins, response_data
    
    except Exception as e:
        logger.error(f"Unexpected error during Atlassian security collection: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return [], None


# For testing purposes
if __name__ == "__main__":
    import os
    import sys
    
    # Add the app directory to the path so we can import app modules
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    
    # Run the collector manually for testing
    bulletins, response = run(
        ingest_url="http://test-url",
        token="test-token"
    )
    
    logger.info(f"Collected {len(bulletins)} bulletins")
    for bulletin in bulletins[:5]:  # Print first 5 for verification
        print(f"Title: {bulletin.content.title}")
        print(f"Published: {bulletin.content.published_at}")
        print(f"Severity: {bulletin.severity}")
        print(f"URL: {bulletin.source.origin_url}")
        print("---")
