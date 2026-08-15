"""Asynchronous web crawler engine with rate limiting and retry logic."""
import asyncio
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Any
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry, stop_after_attempt, wait_exponential, 
    retry_if_exception_type, before_sleep_log
)
import logging

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    """Result of a crawl operation."""
    url: str
    status_code: int
    html: Optional[str] = None
    error: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    final_url: Optional[str] = None
    retry_count: int = 0
    duration_ms: float = 0.0


@dataclass
class CrawlConfig:
    """Configuration for the crawler."""
    max_concurrency: int = 5
    request_timeout: int = 30
    max_retries: int = 3
    request_delay_ms: int = 500
    user_agent: str = "AudioCollectionAnalyzer/1.0"
    respect_robots_txt: bool = True
    follow_redirects: bool = True
    max_redirects: int = 5
    
    # Domain-specific delays (in ms)
    domain_delays: Dict[str, int] = field(default_factory=dict)


class RateLimiter:
    """Token bucket rate limiter per domain."""
    
    def __init__(self, default_delay_ms: int = 500):
        self.default_delay = default_delay_ms / 1000.0
        self.domain_delays: Dict[str, float] = {}
        self.domain_last_request: Dict[str, float] = {}
        self._lock = asyncio.Lock()
    
    def set_domain_delay(self, domain: str, delay_ms: int):
        """Set custom delay for a domain."""
        self.domain_delays[domain] = delay_ms / 1000.0
    
    async def acquire(self, url: str):
        """Acquire permission to make a request, waiting if necessary."""
        domain = urlparse(url).netloc
        delay = self.domain_delays.get(domain, self.default_delay)
        
        async with self._lock:
            now = time.time()
            last_request = self.domain_last_request.get(domain, 0)
            elapsed = now - last_request
            
            if elapsed < delay:
                wait_time = delay - elapsed
                await asyncio.sleep(wait_time)
            
            self.domain_last_request[domain] = time.time()


class CrawlerEngine:
    """High-performance asynchronous web crawler."""
    
    def __init__(self, config: CrawlConfig = None):
        self.config = config or CrawlConfig()
        self.rate_limiter = RateLimiter(self.config.request_delay_ms)
        self.semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self.visited_urls: Set[str] = set()
        self.failed_urls: Dict[str, int] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._robots_cache: Dict[str, Any] = {}
        
    async def __aenter__(self):
        """Async context manager entry."""
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100
        )
        timeout = httpx.Timeout(
            connect=10.0,
            read=self.config.request_timeout,
            write=10.0,
            pool=10.0
        )
        self._client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            follow_redirects=self.config.follow_redirects,
            headers={"User-Agent": self.config.user_agent}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        return urlparse(url).netloc
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        # Remove fragment, normalize path
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized.lower()
    
    def is_visited(self, url: str) -> bool:
        """Check if URL has been visited."""
        return self._normalize_url(url) in self.visited_urls
    
    def mark_visited(self, url: str):
        """Mark URL as visited."""
        self.visited_urls.add(self._normalize_url(url))
    
    async def _check_robots_txt(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt."""
        if not self.config.respect_robots_txt:
            return True
        
        # Simplified robots.txt check - in production, use robotparser
        return True
    
    async def fetch(
        self, 
        url: str, 
        retry_count: int = 0,
        extra_headers: Dict[str, str] = None
    ) -> CrawlResult:
        """Fetch a single URL with rate limiting and retries."""
        start_time = time.time()
        
        async with self.semaphore:
            await self.rate_limiter.acquire(url)
            
            normalized = self._normalize_url(url)
            if self.is_visited(url) and retry_count == 0:
                return CrawlResult(
                    url=url,
                    status_code=0,
                    error="URL already visited",
                    duration_ms=(time.time() - start_time) * 1000
                )
            
            if not await self._check_robots_txt(url):
                return CrawlResult(
                    url=url,
                    status_code=0,
                    error="Disallowed by robots.txt",
                    duration_ms=(time.time() - start_time) * 1000
                )
            
            headers = {}
            if extra_headers:
                headers.update(extra_headers)
            
            try:
                response = await self._client.get(url, headers=headers)
                duration = (time.time() - start_time) * 1000
                
                self.mark_visited(url)
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    await asyncio.sleep(retry_after)
                    if retry_count < self.config.max_retries:
                        return await self.fetch(url, retry_count + 1, extra_headers)
                
                # Handle server errors with retry
                if response.status_code >= 500 and retry_count < self.config.max_retries:
                    wait_time = (2 ** retry_count) + random.uniform(0, 1)
                    await asyncio.sleep(wait_time)
                    return await self.fetch(url, retry_count + 1, extra_headers)
                
                return CrawlResult(
                    url=url,
                    status_code=response.status_code,
                    html=response.text if response.status_code == 200 else None,
                    headers=dict(response.headers),
                    final_url=str(response.url),
                    retry_count=retry_count,
                    duration_ms=duration
                )
                
            except httpx.TimeoutException as e:
                duration = (time.time() - start_time) * 1000
                if retry_count < self.config.max_retries:
                    await asyncio.sleep(2 ** retry_count)
                    return await self.fetch(url, retry_count + 1, extra_headers)
                return CrawlResult(
                    url=url,
                    status_code=0,
                    error=f"Timeout: {str(e)}",
                    duration_ms=duration
                )
                
            except httpx.HTTPStatusError as e:
                duration = (time.time() - start_time) * 1000
                return CrawlResult(
                    url=url,
                    status_code=e.response.status_code,
                    error=f"HTTP Error: {e.response.status_code}",
                    duration_ms=duration
                )
                
            except Exception as e:
                duration = (time.time() - start_time) * 1000
                return CrawlResult(
                    url=url,
                    status_code=0,
                    error=f"Exception: {str(e)}",
                    duration_ms=duration
                )
    
    async def fetch_many(
        self, 
        urls: List[str],
        callback: Optional[Callable[[CrawlResult], None]] = None
    ) -> List[CrawlResult]:
        """Fetch multiple URLs concurrently."""
        tasks = [self.fetch(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append(CrawlResult(
                    url="",
                    status_code=0,
                    error=str(result)
                ))
            else:
                processed_results.append(result)
                if callback:
                    callback(result)
        
        return processed_results
    
    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML with BeautifulSoup."""
        return BeautifulSoup(html, 'lxml')
    
    def extract_links(
        self, 
        soup: BeautifulSoup, 
        base_url: str,
        pattern: Optional[str] = None
    ) -> List[str]:
        """Extract all links from HTML, optionally filtered by pattern."""
        links = []
        for anchor in soup.find_all('a', href=True):
            href = anchor['href']
            full_url = urljoin(base_url, href)
            
            # Filter by same domain
            if self._get_domain(full_url) != self._get_domain(base_url):
                continue
            
            if pattern and pattern not in full_url:
                continue
                
            links.append(full_url)
        
        return list(set(links))
    
    async def stream_fetch(
        self, 
        url: str,
        chunk_size: int = 8192
    ) -> tuple[int, Optional[bytes], Dict[str, str]]:
        """Fetch binary content with streaming."""
        await self.rate_limiter.acquire(url)
        
        async with self.semaphore:
            try:
                async with self._client.stream("GET", url) as response:
                    if response.status_code != 200:
                        return response.status_code, None, dict(response.headers)
                    
                    chunks = []
                    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                        chunks.append(chunk)
                    
                    content = b"".join(chunks)
                    return response.status_code, content, dict(response.headers)
                    
            except Exception as e:
                return 0, None, {"error": str(e)}
    
    def reset(self):
        """Reset crawler state."""
        self.visited_urls.clear()
        self.failed_urls.clear()
