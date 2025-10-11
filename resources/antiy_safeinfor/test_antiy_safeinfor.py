"""Tests for the Antiy SafeInfo collector plugin."""

import pytest
from unittest.mock import Mock, patch
import json
from pathlib import Path

from resources.antiy_safeinfor.collector import AntiySafeInfoCollector, FetchParams


def test_fetch_detail():
    """Test fetching the detailed security announcements."""
    collector = AntiySafeInfoCollector()
    
    # Mock the session.post call to return sample data
    mock_response = Mock()
    mock_response.json.return_value = {
        "status": "success",
        "data": {
            "id": 1365,
            "title": "每日安全简讯（20251011）",
            "content": [
                {
                    "tags": ["游蛇", "银狐", "钓鱼网站"],
                    "refer": ["https://example.com"],
                    "title": "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告",
                    "event_time": "2025-10-11",
                    "description": "安天CERT持续对\"游蛇\"黑产团伙进行跟踪，发现该组织大量仿冒一系列流行应用程序进行钓鱼传播..."
                }
            ],
            "status": "1", 
            "time": "2025-10-11 06:00"
        }
    }
    mock_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'post', return_value=mock_response):
        data = collector.fetch_detail("20251011")
        
        assert data is not None
        assert data["status"] == "success"
        content = data["data"]["content"]
        assert len(content) == 1
        assert content[0]["title"] == "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告"


def test_normalize():
    """Test the normalization of security announcement data."""
    collector = AntiySafeInfoCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    sample_item = {
        "tags": ["游蛇", "银狐", "钓鱼网站"],
        "refer": ["https://example.com"],
        "title": "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告",
        "event_time": "2025-10-11",
        "description": "安天CERT持续对\"游蛇\"黑产团伙进行跟踪，发现该组织大量仿冒一系列流行应用程序进行钓鱼传播..."
    }
    
    bulletin = collector.normalize(sample_item, "20251011")
    
    assert bulletin is not None
    assert bulletin.source.source_slug == "antiy_safeinfor"
    assert "安天威胁情报中心-" in bulletin.content.title
    assert "安天CERT持续对" in bulletin.content.body_text
    assert bulletin.content.language == "zh-CN"
    assert "security_announcement" in bulletin.topics
    assert "tag:游蛇" in bulletin.labels
    assert "tag:银狐" in bulletin.labels


def test_collect():
    """Test the full collection process."""
    collector = AntiySafeInfoCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    # Mock the detail API response
    mock_response = Mock()
    mock_response.json.return_value = {
        "status": "success",
        "data": {
            "id": 1365,
            "title": "每日安全简讯（20251011）",
            "content": [
                {
                    "tags": ["Crimson Collective", "AWS", "窃密攻击"],
                    "refer": ["https://www.rapid7.com/blog/post/..."],
                    "title": "2、Crimson Collective黑客瞄准AWS云实例窃取数据",
                    "event_time": "2025-10-11",
                    "description": "安全研究机构Rapid7披露，黑客组织\"Crimson Collective\"近期针对AWS云环境发起攻击..."
                },
                {
                    "tags": ["Service Finder", "CVE-2025-5947"],
                    "refer": ["https://www.wordfence.com/blog/..."],
                    "title": "3、黑客利用Service Finder主题漏洞获取管理员权限",
                    "event_time": "2025-10-11", 
                    "description": "安全公司Wordfence警告称，黑客正积极利用WordPress高级主题\"Service Finder\"中的关键漏洞..."
                }
            ],
            "status": "1",
            "time": "2025-10-11 06:00"
        }
    }
    mock_response.raise_for_status.return_value = None
    
    with patch.object(collector.session, 'post', return_value=mock_response):
        params = FetchParams(daily_time="20251011")
        bulletins = collector.collect(params)
        
        assert len(bulletins) == 2
        first_bulletin = bulletins[0]
        second_bulletin = bulletins[1]
        
        # Check basic fields for first bulletin
        assert first_bulletin.source.source_slug == "antiy_safeinfor"
        assert "安天威胁情报中心-" in first_bulletin.content.title
        assert "Crimson Collective" in first_bulletin.content.title
        assert "security_announcement" in first_bulletin.topics
        assert "tag:Crimson Collective" in first_bulletin.labels
        assert "tag:AWS" in first_bulletin.labels
        
        # Check basic fields for second bulletin
        assert second_bulletin.source.source_slug == "antiy_safeinfor"
        assert "安天威胁情报中心-" in second_bulletin.content.title
        assert "Service Finder" in second_bulletin.content.title
        assert "安全公司Wordfence" in second_bulletin.content.body_text
        assert "tag:Service Finder" in second_bulletin.labels
        assert "tag:CVE-2025-5947" in second_bulletin.labels


def test_duplicate_handling():
    """Test that duplicate items are properly handled."""
    collector = AntiySafeInfoCollector()
    
    # Clear any existing cache to ensure test isolation
    cache_file = Path(collector.cache_file)
    if cache_file.exists():
        cache_file.unlink()
    
    sample_item = {
        "tags": ["游蛇", "银狐"],
        "refer": ["https://example.com"],
        "title": "1、安天发布《\"游蛇（银狐）\"黑产密集聚仿冒各类流行应用：WPS下载站打假专辑》报告",
        "event_time": "2025-10-11",
        "description": "安天CERT持续对\"游蛇\"黑产团伙进行跟踪..."
    }
    
    # First collection - should process normally
    first_bulletin = collector.normalize(sample_item, "20251011")
    assert first_bulletin is not None
    assert "安天威胁情报中心-" in first_bulletin.content.title
    
    # Second collection with the same item - should return None (skip duplicates)
    second_bulletin = collector.normalize(sample_item, "20251011")
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
    collector._mark_processed("test_id_123")
    
    # Cache should now contain the entry
    updated_cache = collector._load_cache()
    assert "test_id_123" in updated_cache
    assert len(updated_cache) == 1
    
    # Check that cache file was created
    assert cache_file.exists()
    
    # Load the cache again and verify persistence
    reloaded_cache = collector._load_cache()
    assert "test_id_123" in reloaded_cache