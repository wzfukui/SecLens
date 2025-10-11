"""Tests for the Lenovo security advisory collector plugin."""

import pytest
import json
from unittest.mock import Mock, patch

from resources.lenovo_security_advisory.collector import LenovoCollector, FetchParams, _clean_html_content


def test_fetch_list():
    """Test fetching the list of security advisories."""
    collector = LenovoCollector()
    
    # Mock the session.get call to return sample data
    mock_response = Mock()
    mock_response.json.return_value = {
        "statusCode": 200,
        "message": "success",
        "data": {
            "total": 1,
            "data": [
                {
                    "notice_code": "test_code_123",
                    "notice_number": "LEN-123456",
                    "notice_name": "Test Security Advisory",
                    "notice_link": "https://iknow.lenovo.com.cn/detail/123456?type=undefined&keyword=123456&keyWordId=",
                    "notice_cves": "CVE-2023-1234, CVE-2023-5678",
                    "publish_at": "2023-10-10 10:00:00",
                    "last_at": "2023-10-10 10:00:00",
                    "created_at": "2023-10-10 10:00:00",
                    "updated_at": None
                }
            ]
        }
    }
    mock_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'get', return_value=mock_response):
        params = FetchParams(page_index=1, page_size=1)
        items = collector.fetch_list(params)
        
        assert len(items) == 1
        assert items[0]["notice_number"] == "LEN-123456"


def test_extract_knowledge_no_from_url():
    """Test extracting knowledge number from URL."""
    collector = LenovoCollector()
    
    url = "https://iknow.lenovo.com.cn/detail/431977?type=undefined&keyword=431977&keyWordId="
    knowledge_no = collector.extract_knowledge_no_from_url(url)
    
    assert knowledge_no == "431977"


def test_collect():
    """Test the full collection process."""
    collector = LenovoCollector()
    
    # Mock the session.get call for the list API
    mock_list_response = Mock()
    mock_list_response.json.return_value = {
        "statusCode": 200,
        "message": "success",
        "data": {
            "total": 1,
            "data": [
                {
                    "notice_code": "test_code_123",
                    "notice_number": "LEN-123456",
                    "notice_name": "Test Security Advisory",
                    "notice_link": "https://iknow.lenovo.com.cn/detail/123456?type=undefined&keyword=123456&keyWordId=",
                    "notice_cves": "CVE-2023-1234, CVE-2023-5678",
                    "publish_at": "2023-10-10 10:00:00",
                    "last_at": "2023-10-10 10:00:00",
                    "created_at": "2023-10-10 10:00:00",
                    "updated_at": None
                }
            ]
        }
    }
    mock_list_response.raise_for_status.return_value = None
    
    # Mock the session.get call for the detail API
    mock_detail_response = Mock()
    mock_detail_response.json.return_value = {
        "code": 200,
        "msg": None,
        "data": {
            "uid": "0x123456",
            "knowledgeNo": "123456",
            "title": "Test Security Advisory Detail",
            "content": "<html><body><h1>Test Title</h1><p>Test content with <strong>formatting</strong>.</p><script>alert('test');</script></body></html>",
            "digest": "Test advisory summary",
            "createTime": "2023-10-10 10:00:00",
            "updateTime": None,
            "lineCategoryName": "Test Category",
            "keyWords": ["test", "advisory", "security"]
        }
    }
    mock_detail_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'get', side_effect=[mock_list_response, mock_detail_response]):
        params = FetchParams(page_index=1, page_size=1)
        bulletins = collector.collect(params)
        
        assert len(bulletins) == 1
        bulletin = bulletins[0]
        
        # Check that the bulletin was created correctly
        assert bulletin.source.source_slug == "lenovo_security_advisory"
        assert bulletin.source.external_id == "LEN-123456"
        assert "Test Security Advisory Detail" in bulletin.content.title
        assert "Test advisory summary" in bulletin.content.summary
        # Check that HTML was cleaned (script tag should be removed)
        assert "alert('test')" not in bulletin.content.body_text
        # Check that content elements are properly extracted (with newlines)
        assert "Test Title" in bulletin.content.body_text
        assert "Test content with" in bulletin.content.body_text
        assert "formatting" in bulletin.content.body_text
        # Check that original HTML is preserved in extra
        assert "html_content" in bulletin.extra
        assert "<script>" in bulletin.extra["html_content"]


def test_html_cleaning():
    """Test HTML cleaning functionality."""
    # Test with complex HTML content
    html_content = """
    <html>
        <head><title>Test</title></head>
        <body>
            <h1>Header content</h1>
            <p>Paragraph with <strong>bold text</strong> and <em>emphasis</em>.</p>
            <script>alert('remove this');</script>
            <style>.remove { display: none; }</style>
            <div>Final content</div>
        </body>
    </html>
    """
    
    cleaned = _clean_html_content(html_content)
    
    # Should remove script and style tags
    assert "alert('remove this')" not in cleaned
    assert ".remove { display: none; }" not in cleaned
    
    # Should preserve meaningful content
    assert "Header content" in cleaned
    assert "Paragraph with" in cleaned
    assert "bold text" in cleaned
    assert "emphasis" in cleaned
    assert "Final content" in cleaned
    
    # Test with None input
    assert _clean_html_content(None) == ""
    
    # Test with empty string
    assert _clean_html_content("") == ""
    
    # Test fallback with invalid HTML
    assert "fallback content" in _clean_html_content("fallback content")