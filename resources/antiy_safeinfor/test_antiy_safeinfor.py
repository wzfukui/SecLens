"""Tests for the Antiy SafeInfo collector plugin."""

import pytest
from unittest.mock import Mock, patch
import json
from pathlib import Path

from resources.antiy_safeinfor.collector import AntiySafeInfoCollector, FetchParams


def test_fetch_list():
    """Test fetching the list of security announcements."""
    collector = AntiySafeInfoCollector()
    
    # Mock the session.post call to return sample data
    mock_response = Mock()
    mock_response.json.return_value = {
        "status": "success",
        "data": {
            "current": [
                {
                    "id": 1365,
                    "title": "每日安全简讯（20251011）",
                    "content": "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告 2、Crimson Collective黑客瞄准AWS云实例窃取数据 3、黑客利用Service Finder主题漏洞获取管理员权限",
                    "daily_time": "20251011",
                    "status": "1",
                    "time": "2025-10-11 06:00",
                    "tags": []
                }
            ]
        }
    }
    mock_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'post', return_value=mock_response):
        params = FetchParams(page=1, page_size=1)
        items = collector.fetch_list(params)
        
        assert len(items) == 1
        assert items[0]["title"] == "每日安全简讯（20251011）"
        assert items[0]["id"] == 1365


def test_normalize():
    """Test the normalization of security announcement data."""
    collector = AntiySafeInfoCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    sample_item = {
        "id": 1365,
        "title": "每日安全简讯（20251011）",
        "content": "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告 2、Crimson Collective黑客瞄准AWS云实例窃取数据",
        "daily_time": "20251011",
        "status": "1",
        "time": "2025-10-11 06:00",
        "tags": []
    }
    
    bulletin = collector.normalize(sample_item)
    
    assert bulletin is not None
    assert bulletin.source.source_slug == "antiy_safeinfor"
    assert bulletin.source.external_id == "1365"
    assert "安天威胁情报中心-每日安全简讯（20251011）" in bulletin.content.title
    assert bulletin.content.language == "zh-CN"
    assert "安天发布" in bulletin.content.body_text
    assert "Crimson Collective" in bulletin.content.body_text
    assert "security_announcement" in bulletin.topics
    assert "antiy" in bulletin.labels


def test_collect():
    """Test the full collection process."""
    collector = AntiySafeInfoCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    # Mock the list API response
    mock_response = Mock()
    mock_response.json.return_value = {
        "status": "success",
        "data": {
            "current": [
                {
                    "id": 1365,
                    "title": "每日安全简讯（20251011）",
                    "content": "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告 2、Crimson Collective黑客瞄准AWS云实例窃取数据",
                    "daily_time": "20251011",
                    "status": "1",
                    "time": "2025-10-11 06:00",
                    "tags": []
                }
            ]
        }
    }
    mock_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'post', return_value=mock_response):
        params = FetchParams(page=1, page_size=1)
        bulletins = collector.collect(params)
        
        assert len(bulletins) == 1
        bulletin = bulletins[0]
        
        # Check basic fields
        assert bulletin.source.source_slug == "antiy_safeinfor"
        assert bulletin.source.external_id == "1365"
        assert "安天威胁情报中心-" in bulletin.content.title
        assert "安天发布" in bulletin.content.body_text
        assert "Crimson Collective" in bulletin.content.body_text
        
        # Check topics
        assert "security_announcement" in bulletin.topics
        
        # Check labels
        assert "antiy" in bulletin.labels
        assert "daily:20251011" in bulletin.labels


def test_duplicate_handling():
    """Test that duplicate items are properly handled."""
    collector = AntiySafeInfoCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    sample_item = {
        "id": 1365,
        "title": "每日安全简讯（20251011）",
        "content": "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告",
        "daily_time": "20251011",
        "status": "1",
        "time": "2025-10-11 06:00",
        "tags": []
    }
    
    # First collection - should process normally
    first_bulletin = collector.normalize(sample_item)
    assert first_bulletin is not None
    assert first_bulletin.source.external_id == "1365"
    
    # Second collection with the same item - should return None (skip duplicates)
    second_bulletin = collector.normalize(sample_item)
    assert second_bulletin is None


def test_cache_functionality():
    """Test the cache loading and saving functionality."""
    collector = AntiySafeInfoCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    # Initially cache should be empty
    initial_cache = collector._load_cache()
    assert len(initial_cache) == 0
    
    # Add an entry to the cache
    collector._mark_processed(12345)
    
    # Cache should now contain the entry
    updated_cache = collector._load_cache()
    assert 12345 in updated_cache
    assert len(updated_cache) == 1
    
    # Check that cache file was created
    assert cache_file.exists()
    
    # Load the cache again and verify persistence
    reloaded_cache = collector._load_cache()
    assert 12345 in reloaded_cache