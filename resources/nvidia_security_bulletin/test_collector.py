"""Tests for NVIDIA security bulletin collector plugin."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from resources.nvidia_security_bulletin.collector import NVIDIACollector, _extract_cve_ids, _clean_html_content


@pytest.fixture
def mock_session():
    """Mock requests session for testing."""
    session = Mock(spec=requests.Session)
    session.headers = {}
    return session


def test_extract_cve_ids():
    """Test CVE ID extraction from various formats."""
    # Single CVE
    assert _extract_cve_ids("CVE-2025-1234") == ["CVE-2025-1234"]
    
    # Multiple CVEs comma-separated
    input_str = "CVE-2025-1234, CVE-2025-1235, CVE-2025-1236"
    expected = ["CVE-2025-1234", "CVE-2025-1235", "CVE-2025-1236"]
    assert _extract_cve_ids(input_str) == expected
    
    # Multiple CVEs semicolon-separated
    input_str = "CVE-2025-1234; CVE-2025-1235; CVE-2025-1236"
    expected = ["CVE-2025-1234", "CVE-2025-1235", "CVE-2025-1236"]
    assert _extract_cve_ids(input_str) == expected
    
    # Edge cases
    assert _extract_cve_ids(None) == []
    assert _extract_cve_ids("") == []
    assert _extract_cve_ids("random text") == []


def test_clean_html_content():
    """Test HTML content cleaning."""
    html_input = "<p>This is <b>bold</b> text.</p><script>alert('test');</script>"
    expected = "This is bold text."
    assert _clean_html_content(html_input) == expected
    
    # Test with None input
    assert _clean_html_content(None) == ""
    
    # Test with empty input
    assert _clean_html_content("") == ""


def test_fetch_list():
    """Test fetching the list of security bulletins."""
    # Mock response data similar to the example provided
    mock_response_data = {
        "columns": {
            "tableColumns": {
                "title": {"en": "Title"},
                "bulletin id": {"en": "Bulletin ID"},
                "severity": {"en": "Severity"},
                "cve identifier(s)": "CVE Identifier(s)",
                "publish date": {"en": "Publish Date"},
                "last updated": {"en": "Last Updated"}
            },
            "columnType": {
                "publish date": "Date",
                "last updated": "Date"
            }
        },
        "footer": {"en": ""},
        "data": [
            {
                "title": "<a href='https://nvidia.custhelp.com/app/answers/detail/a_id/5703' target='_blank'>NVIDIA GPU Display Driver - October 2025</a>",
                "bulletin id": "5703",
                "severity": "High",
                "cve identifier(s)": "CVE-2025-23280, CVE-2025-23282, CVE-2025-23300",
                "publish date": "09 Oct 2025",
                "last updated": "09 Oct 2025"
            },
            {
                "title": "<a href='https://nvidia.custhelp.com/app/answers/detail/a_id/5705' target='_blank'>NVIDIA License System - September 2025</a>",
                "bulletin id": "5705",
                "severity": "High",
                "cve identifier(s)": "CVE-2025-23291, CVE-2025-23292",
                "publish date": "30 Sep 2025",
                "last updated": "30 Sep 2025"
            }
        ]
    }
    
    with patch('requests.Session') as mock_session_class:
        mock_session_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_session_instance.get.return_value = mock_response
        mock_session_class.return_value = mock_session_instance
        
        collector = NVIDIACollector(session=mock_session_instance)
        items = collector.fetch_list()
        
        # Should return up to 10 items (in this case only 2)
        assert len(items) == 2
        
        # Check first item
        first_item = items[0]
        assert first_item["bulletin id"] == "5703"
        assert "NVIDIA GPU Display Driver - October 2025" in first_item["title"]
        assert "CVE-2025-23280" in first_item["cve identifier(s)"]


def test_normalize():
    """Test normalizing a bulletin item."""
    # Test item similar to the example
    test_item = {
        "title": "<a href='https://nvidia.custhelp.com/app/answers/detail/a_id/5703' target='_blank'>NVIDIA GPU Display Driver - October 2025</a>",
        "bulletin id": "5703",
        "severity": "High",
        "cve identifier(s)": "CVE-2025-23280, CVE-2025-23282, CVE-2025-23300",
        "publish date": "09 Oct 2025",
        "last updated": "09 Oct 2025"
    }
    
    with patch('requests.Session') as mock_session_class:
        mock_session_instance = Mock()
        mock_session_class.return_value = mock_session_instance
        
        collector = NVIDIACollector(session=mock_session_instance)
        bulletin = collector.normalize(test_item)
        
        # Verify the normalized bulletin
        assert bulletin.source.external_id == "5703"
        assert bulletin.source.source_slug == "nvidia_security_bulletin"
        assert "NVIDIA GPU Display Driver - October 2025" in bulletin.content.title
        assert bulletin.severity == "high"  # Should be normalized to lowercase
        assert "cve:CVE-2025-23280" in [label for label in bulletin.labels if label.startswith("cve:")]
        
        # The CVE IDs should be in the raw data
        assert "CVE-2025-23280" in bulletin.extra.get("cve_identifiers_raw", "")


def test_cursor_functionality(tmp_path):
    """Test cursor functionality for tracking seen bulletin IDs."""
    # Create a temporary state file
    state_file = tmp_path / ".nvidia_cursor"
    
    with patch('requests.Session') as mock_session_class:
        mock_session_instance = Mock()
        mock_session_class.return_value = mock_session_instance
        
        collector = NVIDIACollector(session=mock_session_instance, state_path=state_file)
        
        # Save a set of IDs
        test_ids = {"5703", "5705", "5707"}
        collector.save_cursor(test_ids)
        
        # Load them back
        loaded_ids = collector.load_cursor()
        
        assert loaded_ids == test_ids


def test_collect_with_seen_ids(tmp_path):
    """Test that collect method filters out already seen bulletin IDs."""
    # Mock response data
    mock_response_data = {
        "columns": {
            "tableColumns": {
                "title": {"en": "Title"},
                "bulletin id": {"en": "Bulletin ID"},
                "severity": {"en": "Severity"},
                "cve identifier(s)": "CVE Identifier(s)",
                "publish date": {"en": "Publish Date"},
                "last updated": {"en": "Last Updated"}
            },
            "columnType": {
                "publish date": "Date",
                "last updated": "Date"
            }
        },
        "footer": {"en": ""},
        "data": [
            {
                "title": "<a href='https://nvidia.custhelp.com/app/answers/detail/a_id/5703' target='_blank'>NVIDIA GPU Display Driver - October 2025</a>",
                "bulletin id": "5703",  # This ID is already seen
                "severity": "High",
                "cve identifier(s)": "CVE-2025-23280",
                "publish date": "09 Oct 2025",
                "last updated": "09 Oct 2025"
            },
            {
                "title": "<a href='https://nvidia.custhelp.com/app/answers/detail/a_id/5704' target='_blank'>NVIDIA Nsight Graphics - September 2025</a>",
                "bulletin id": "5704",  # This ID is new
                "severity": "Medium",
                "cve identifier(s)": "CVE-2025-23355",
                "publish date": "30 Sep 2025",
                "last updated": "30 Sep 2025"
            }
        ]
    }
    
    # Create a temporary state file with one already seen ID
    state_file = tmp_path / ".nvidia_cursor"
    state_file.write_text(json.dumps(["5703"]), encoding="utf-8")
    
    with patch('requests.Session') as mock_session_class:
        mock_session_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        mock_session_instance.get.return_value = mock_response
        mock_session_class.return_value = mock_session_instance
        
        collector = NVIDIACollector(session=mock_session_instance, state_path=state_file)
        bulletins = collector.collect()
        
        # Should only return 1 bulletin (the new one, not the already seen one)
        assert len(bulletins) == 1
        assert bulletins[0].source.external_id == "5704"
        
        # Check that the cursor was updated with both IDs
        updated_ids = collector.load_cursor()
        assert "5703" in updated_ids
        assert "5704" in updated_ids


if __name__ == "__main__":
    pytest.main([__file__])