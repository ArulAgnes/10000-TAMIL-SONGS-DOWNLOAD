"""Tests for the crawler module."""
import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio

from app.crawler.engine import CrawlerEngine, CrawlConfig, CrawlResult
from app.crawler.audio_crawler import AudioWebsiteCrawler, AlbumInfo
from app.models.schemas import CrawlerConfig as CrawlerConfigSchema


class TestCrawlerEngine:
    """Tests for CrawlerEngine."""
    
    @pytest.fixture
    def config(self):
        return CrawlConfig(
            max_concurrency=2,
            request_timeout=10,
            max_retries=2,
            request_delay_ms=100
        )
    
    @pytest.mark.asyncio
    async def test_fetch_success(self, config):
        """Test successful fetch."""
        async with CrawlerEngine(config) as engine:
            with patch.object(engine._client, 'get') as mock_get:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = "<html><body>Test</body></html>"
                mock_response.headers = {}
                mock_response.url = "http://example.com"
                mock_get.return_value = mock_response
                
                result = await engine.fetch("http://example.com")
                
                assert result.status_code == 200
                assert result.html == "<html><body>Test</body></html>"
    
    @pytest.mark.asyncio
    async def test_fetch_error(self, config):
        """Test fetch with error."""
        async with CrawlerEngine(config) as engine:
            with patch.object(engine._client, 'get') as mock_get:
                mock_get.side_effect = Exception("Connection error")
                
                result = await engine.fetch("http://example.com")
                
                assert result.status_code == 0
                assert "Connection error" in result.error
    
    def test_normalize_url(self, config):
        """Test URL normalization."""
        engine = CrawlerEngine(config)
        
        # Test normalization
        assert engine._normalize_url("HTTP://Example.COM/Page") == "http://example.com/page"
        assert engine._normalize_url("http://example.com/page#fragment") == "http://example.com/page"
    
    def test_is_visited(self, config):
        """Test visited URL tracking."""
        engine = CrawlerEngine(config)
        
        assert not engine.is_visited("http://example.com")
        engine.mark_visited("http://example.com")
        assert engine.is_visited("http://example.com")


class TestAudioWebsiteCrawler:
    """Tests for AudioWebsiteCrawler."""
    
    @pytest.fixture
    def crawler(self):
        config = CrawlerConfigSchema(
            max_concurrency=2,
            request_delay_ms=100
        )
        return AudioWebsiteCrawler(config)
    
    def test_generate_year_urls(self, crawler):
        """Test year URL generation."""
        urls = crawler.generate_year_urls(
            "https://example.com/songs/{year}",
            2020,
            2022
        )
        
        assert len(urls) == 3
        assert urls[0] == (2020, "https://example.com/songs/2020")
        assert urls[1] == (2021, "https://example.com/songs/2021")
        assert urls[2] == (2022, "https://example.com/songs/2022")
    
    def test_generate_year_urls_without_placeholder(self, crawler):
        """Test URL generation without placeholder."""
        urls = crawler.generate_year_urls(
            "https://example.com/songs",
            2020,
            2021
        )
        
        assert urls[0] == (2020, "https://example.com/songs/2020")

    def test_generate_year_urls_from_trailing_year(self, crawler):
        """Replace the final year in a category URL."""
        urls = crawler.generate_year_urls(
            "https://example.com/category/latest-tamil-songs/2026",
            2024,
            2026
        )

        assert urls == [
            (2024, "https://example.com/category/latest-tamil-songs/2024"),
            (2025, "https://example.com/category/latest-tamil-songs/2025"),
            (2026, "https://example.com/category/latest-tamil-songs/2026"),
        ]
    
    def test_sanitize_filename(self, crawler):
        """Test filename sanitization."""
        # This would need to be exposed or tested through download
        pass


class TestIntegration:
    """Integration tests."""
    
    @pytest.mark.asyncio
    async def test_crawl_flow(self):
        """Test complete crawl flow with mock responses."""
        # This would test the full crawl process
        pass
