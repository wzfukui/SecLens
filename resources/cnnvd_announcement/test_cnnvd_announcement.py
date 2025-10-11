"""Tests for the CNNVD announcement collector plugin."""

import pytest
from unittest.mock import Mock, patch
import json
from pathlib import Path

from resources.cnnvd_announcement.collector import CNNVDAnnouncementCollector, FetchParams


def test_fetch_list():
    """Test fetching the list of announcements."""
    collector = CNNVDAnnouncementCollector()
    
    # Mock the session.post call to return sample data
    mock_response = Mock()
    mock_response.json.return_value = {
        "code": 200,
        "success": True,
        "message": "操作成功",
        "data": {
            "total": 2,
            "records": [
                {
                    "createUname": "zhangdan",
                    "publishTime": "2025-10-09 14:50:57",
                    "warnName": "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报",
                    "warnId": "09e4ab8c398f4fd391dcc6303f93b589",
                    "contentStr": None
                },
                {
                    "createUname": "zhangdan",
                    "publishTime": "2025-09-11 14:45:10",
                    "warnName": "【漏洞通报】CNNVD关于微软多个安全漏洞的通报",
                    "warnId": "879e75900c024d8c98e9ed9e6222af11",
                    "contentStr": None
                }
            ],
            "pageIndex": 1,
            "pageSize": 20
        },
        "time": "2025-10-11 19:01:51"
    }
    mock_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'post', return_value=mock_response):
        params = FetchParams(page_index=1, page_size=2)
        items = collector.fetch_list(params)
        
        assert len(items) == 2
        assert items[0]["warnName"] == "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报"
        assert items[0]["warnId"] == "09e4ab8c398f4fd391dcc6303f93b589"


def test_fetch_detail():
    """Test fetching detailed announcement information."""
    collector = CNNVDAnnouncementCollector()
    
    # Mock the session.post call for detail API with multipart form data
    mock_response = Mock()
    mock_response.json.return_value = {
        "code": 200,
        "success": True,
        "message": "操作成功",
        "data": {
            "createUname": "zhangdan",
            "publishTime": "2025-10-09 14:50:57",
            "warnName": "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报",
            "enclosureContent": "<p>Test announcement content about Redis vulnerability.</p>",
            "warnId": "09e4ab8c398f4fd391dcc6303f93b589"
        },
        "time": "2025-10-11 19:00:58"
    }
    mock_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'post', return_value=mock_response):
        detail = collector.fetch_detail("09e4ab8c398f4fd391dcc6303f93b589")
        
        assert detail is not None
        assert detail["warnName"] == "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报"
        assert "Redis vulnerability" in detail["enclosureContent"]


def test_collect():
    """Test the full collection process."""
    collector = CNNVDAnnouncementCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    # Mock the list API response
    mock_list_response = Mock()
    mock_list_response.json.return_value = {
        "code": 200,
        "success": True,
        "message": "操作成功",
        "data": {
            "total": 1,
            "records": [
                {
                    "createUname": "zhangdan",
                    "publishTime": "2025-10-09 14:50:57",
                    "warnName": "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报",
                    "warnId": "09e4ab8c398f4fd391dcc6303f93b589",
                    "contentStr": None
                }
            ],
            "pageIndex": 1,
            "pageSize": 1
        },
        "time": "2025-10-11 19:01:51"
    }
    mock_list_response.raise_for_status.return_value = None
    
    # Mock the detail API response
    mock_detail_response = Mock()
    mock_detail_response.json.return_value = {
        "code": 200,
        "success": True,
        "message": "操作成功",
        "data": {
            "createUname": "zhangdan",
            "publishTime": "2025-10-09 14:50:57",
            "warnName": "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报",
            "enclosureContent": "<p>Detailed announcement content about Redis vulnerability.</p>",
            "warnId": "09e4ab8c398f4fd391dcc6303f93b589"
        },
        "time": "2025-10-11 19:00:58"
    }
    mock_detail_response.raise_for_status.return_value = None
    
    # Patch both API calls
    with patch.object(collector.session, 'post', side_effect=[mock_list_response, mock_detail_response]):
        params = FetchParams(page_index=1, page_size=1)
        bulletins = collector.collect(params)
        
        assert len(bulletins) == 1
        bulletin = bulletins[0]
        
        # Check basic fields
        assert bulletin.source.source_slug == "cnnvd_announcement"
        assert bulletin.source.external_id == "09e4ab8c398f4fd391dcc6303f93b589"
        assert "Redis资源管理错误漏洞" in bulletin.content.title
        assert bulletin.severity == "info"
        assert "Redis vulnerability" in bulletin.content.body_text
        
        # Check topics
        assert "cnnvd_announcement" in bulletin.topics
        assert "vulnerability_alert" in bulletin.topics
        
        # Check labels
        assert "cnnvd" in bulletin.labels
        assert "cnnvd_announcement" in bulletin.labels


def test_duplicate_handling():
    """Test that duplicate warnIds are properly handled."""
    collector = CNNVDAnnouncementCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    # First collection - should process normally
    mock_list_response = Mock()
    mock_list_response.json.return_value = {
        "code": 200,
        "success": True,
        "message": "操作成功",
        "data": {
            "total": 1,
            "records": [
                {
                    "createUname": "zhangdan",
                    "publishTime": "2025-10-09 14:50:57",
                    "warnName": "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报",
                    "warnId": "09e4ab8c398f4fd391dcc6303f93b589",
                    "contentStr": None
                }
            ],
            "pageIndex": 1,
            "pageSize": 1
        },
        "time": "2025-10-11 19:01:51"
    }
    mock_list_response.raise_for_status.return_value = None
    
    mock_detail_response = Mock()
    mock_detail_response.json.return_value = {
        "code": 200,
        "success": True,
        "message": "操作成功",
        "data": {
            "createUname": "zhangdan",
            "publishTime": "2025-10-09 14:50:57",
            "warnName": "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报",
            "enclosureContent": "<p>Detailed announcement content about Redis vulnerability.</p>",
            "warnId": "09e4ab8c398f4fd391dcc6303f93b589"
        },
        "time": "2025-10-11 19:00:58"
    }
    mock_detail_response.raise_for_status.return_value = None
    
    # First collection - item should be processed normally
    with patch.object(collector.session, 'post', side_effect=[mock_list_response, mock_detail_response]):
        params = FetchParams(page_index=1, page_size=1)
        bulletins = collector.collect(params)
        
        assert len(bulletins) == 1
        first_bulletin = bulletins[0]
        assert not first_bulletin.extra.get("skipped", False)
    
    # Reset the mock for the second collection
    mock_list_response2 = Mock()
    mock_list_response2.json.return_value = {
        "code": 200,
        "success": True,
        "message": "操作成功",
        "data": {
            "total": 1,
            "records": [
                {
                    "createUname": "zhangdan",
                    "publishTime": "2025-10-09 14:50:57",
                    "warnName": "【漏洞通报】CNNVD关于Redis资源管理错误漏洞的通报",
                    "warnId": "09e4ab8c398f4fd391dcc6303f93b589",  # Same ID as before
                    "contentStr": None
                }
            ],
            "pageIndex": 1,
            "pageSize": 1
        },
        "time": "2025-10-11 19:01:51"
    }
    mock_list_response2.raise_for_status.return_value = None
    
    # Second collection - item should be filtered out due to duplicate warnId
    with patch.object(collector.session, 'post', return_value=mock_list_response2):
        params = FetchParams(page_index=1, page_size=1)
        bulletins = collector.collect(params)
        
        # Should have 0 bulletins because duplicates are filtered out
        assert len(bulletins) == 0


def test_cache_functionality():
    """Test the cache loading and saving functionality."""
    collector = CNNVDAnnouncementCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    # Initially cache should be empty
    initial_cache = collector._load_cache()
    assert len(initial_cache) == 0
    
    # Add an entry to the cache
    collector._mark_processed("test_warn_id_123")
    
    # Cache should now contain the entry
    updated_cache = collector._load_cache()
    assert "test_warn_id_123" in updated_cache
    assert len(updated_cache) == 1
    
    # Check that cache file was created
    assert cache_file.exists()
    
    # Load the cache again and verify persistence
    reloaded_cache = collector._load_cache()
    assert "test_warn_id_123" in reloaded_cache