"""Test cases for Atlassian Security Advisories Collector."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime

from plugins.atlassian_security.collector import (
    run,
    extract_cve_details_from_json,
    parse_atlassian_date,
    fetch_additional_details_from_jira,
    filter_recent_cves,
    create_bulletin_from_cve,
    fetch_atlassian_security_data
)
from app.schemas import BulletinCreate


# Mock data for testing
from datetime import datetime, timezone

MOCK_JSON_RESPONSE = {
    "products": {
        "Jira Software Data Center": {
            "versions": {
                "9.10.0": [{"CVE-2023-46604": "AFFECTED"}]
            }
        }
    },
    "cve_metadata": {
        "CVE-2023-46604": {
            "cve_summary": "Test CVE Summary",
            "cve_description": "Test CVE Description",
            "cve_publish_date": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000+0000'),  # Today's date to pass filter
            "cve_severity": 7.5,
            "atl_tracking_url": "https://jira.atlassian.com/browse/JSWSERVER-22148"
        }
    }
}


def test_parse_atlassian_date():
    """Test parsing of Atlassian date format."""
    date_str = "2023-11-21T18:03:05.000+0000"
    result = parse_atlassian_date(date_str)
    assert result is not None
    assert result.year == 2023
    assert result.month == 11
    assert result.day == 21


def test_extract_cve_details_from_json():
    """Test extraction of CVE details from JSON."""
    result = extract_cve_details_from_json(MOCK_JSON_RESPONSE)
    assert len(result) == 1
    cve = result[0]
    assert cve['cve_id'] == 'CVE-2023-46604'
    assert cve['summary'] == 'Test CVE Summary'
    assert cve['description'] == 'Test CVE Description'
    assert cve['severity'] == 7.5
    assert cve['tracking_url'] == 'https://jira.atlassian.com/browse/JSWSERVER-22148'


def test_filter_recent_cves():
    """Test filtering of recent CVEs."""
    # Create a mock CVE list with various dates
    from datetime import timedelta
    
    cve_list = [
        {
            'cve_id': 'CVE-1',
            'publish_date': datetime.now(timezone.utc) - timedelta(days=5),  # 5 days ago
        },
        {
            'cve_id': 'CVE-2',
            'publish_date': datetime.now(timezone.utc) - timedelta(days=45),  # 45 days ago (too old for 30-day filter)
        }
    ]
    
    result = filter_recent_cves(cve_list, days=30)  # Changed from 10 to 30 days
    assert len(result) == 1
    assert result[0]['cve_id'] == 'CVE-1'


def test_create_bulletin_from_cve():
    """Test creation of bulletin from CVE info."""
    cve_info = {
        'cve_id': 'CVE-2023-46604',
        'summary': 'Test CVE Summary',
        'description': 'Test CVE Description',
        'publish_date': datetime.utcnow(),
        'severity': 7.5,
        'tracking_url': 'https://jira.atlassian.com/browse/JSWSERVER-22148',
        'affected_products': [
            {'product': 'Jira Software Data Center', 'version': '9.10.0', 'status': 'AFFECTED'}
        ]
    }
    
    bulletin = create_bulletin_from_cve(cve_info)
    assert isinstance(bulletin, BulletinCreate)
    assert bulletin.source.source_slug == 'atlassian_security'
    assert bulletin.source.external_id == 'CVE-2023-46604'
    assert bulletin.content.title == 'Test CVE Summary'
    assert bulletin.content.summary == 'Test CVE Summary'
    assert 'Test CVE Description' in bulletin.content.body_text
    assert bulletin.severity == '7.5'
    assert 'jira_software_data_center' in bulletin.labels


@patch('plugins.atlassian_security.collector.requests.get')
def test_fetch_atlassian_security_data(mock_get):
    """Test fetching data from Atlassian API."""
    mock_response = Mock()
    mock_response.json.return_value = MOCK_JSON_RESPONSE
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response
    
    result = fetch_atlassian_security_data()
    assert result == MOCK_JSON_RESPONSE


@patch('plugins.atlassian_security.collector.requests.Session.post')
@patch('plugins.atlassian_security.collector.fetch_atlassian_security_data')
def test_run_function(mock_fetch_data, mock_post):
    """Test the main run function."""
    # Mock the API response
    mock_fetch_data.return_value = MOCK_JSON_RESPONSE
    # Mock the ingestion endpoint response
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"accepted": 3, "duplicates": 0}
    mock_post.return_value = mock_response

    bulletins, response = run("http://test-url", "test-token")

    assert isinstance(bulletins, list)
    assert len(bulletins) > 0
    assert isinstance(bulletins[0], BulletinCreate)
    # The response should be the mocked response from the API call, not the raw data
    mock_post.assert_called_once()


@patch('plugins.atlassian_security.collector.requests.get')
def test_fetch_additional_details_from_jira_success(mock_get):
    """Test fetching additional details from JIRA page."""
    # Mock HTML response with details-module
    mock_html = '''
    <html>
    <body>
        <div id="details-module" class="module toggle-wrap">
            <div class="mod-content">
                <p>This is detailed information about the issue</p>
                <ul><li>Step 1</li><li>Step 2</li></ul>
            </div>
        </div>
    </body>
    </html>
    '''
    
    mock_response = Mock()
    mock_response.content = mock_html
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response
    
    result = fetch_additional_details_from_jira("https://jira.atlassian.com/browse/TEST-123")
    assert result is not None
    assert "detailed information about the issue" in result


@patch('plugins.atlassian_security.collector.requests.get')
def test_fetch_additional_details_from_jira_fallback(mock_get):
    """Test fetching additional details from JIRA page with fallback to issue-container."""
    # Mock HTML response with issue-container but no details-module
    mock_html = '''
    <html>
    <body>
        <div class="issue-container">
            <p>This is issue container content</p>
            <div>More details here</div>
        </div>
    </body>
    </html>
    '''
    
    mock_response = Mock()
    mock_response.content = mock_html
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response
    
    result = fetch_additional_details_from_jira("https://jira.atlassian.com/browse/TEST-123")
    assert result is not None
    assert "issue container content" in result


@patch('plugins.atlassian_security.collector.requests.get')
def test_fetch_additional_details_from_jira_failure(mock_get):
    """Test handling of failure when fetching JIRA details."""
    mock_get.side_effect = Exception("Network error")
    
    result = fetch_additional_details_from_jira("https://jira.atlassian.com/browse/TEST-123")
    assert result is None


def test_create_bulletin_from_cve_with_empty_tracking_url():
    """Test creating bulletin when tracking URL is empty."""
    cve_info = {
        'cve_id': 'CVE-2023-46604',
        'summary': 'Test CVE Summary',
        'description': 'Test CVE Description',
        'publish_date': datetime.utcnow(),
        'severity': 7.5,
        'tracking_url': '',
        'affected_products': []
    }
    
    bulletin = create_bulletin_from_cve(cve_info)
    assert bulletin.source.origin_url is None