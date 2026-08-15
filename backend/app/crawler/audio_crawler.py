"""Audio website crawler with year-based pagination and album discovery."""
import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable, AsyncGenerator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import structlog

from app.crawler.engine import CrawlerEngine, CrawlConfig, CrawlResult
from app.models.schemas import CrawlerConfig as CrawlerConfigSchema

logger = structlog.get_logger()


@dataclass
class AlbumInfo:
    """Discovered album information."""
    title: str
    url: str
    year: int
    category_url: str
    discovery_page: int
    artist: Optional[str] = None
    cover_image: Optional[str] = None


@dataclass
class SongInfo:
    """Discovered song information."""
    title: str
    url: Optional[str]
    track_number: Optional[int] = None
    duration: Optional[str] = None
    artist: Optional[str] = None
    audio_resources: List["AudioResourceInfo"] = field(default_factory=list)


@dataclass
class AudioResourceInfo:
    """Audio resource information."""
    url: str
    format: Optional[str]
    bitrate: Optional[str]
    file_size: Optional[int]


@dataclass
class AlbumDetails:
    """Complete album details."""
    title: str
    url: str
    release_year: Optional[int]
    artist: Optional[str]
    music_director: Optional[str]
    genre: Optional[str]
    description: Optional[str]
    cover_image_url: Optional[str]
    zip_url: Optional[str]
    songs: List[SongInfo]
    audio_resources: List[AudioResourceInfo]


class AudioWebsiteCrawler:
    """Crawler specialized for audio websites with year-based navigation."""
    
    # Dedicated song list item containers. The word boundary guards against
    # matching broad "song" classes (song-info, song-meta, song-actions,
    # related-song-item) that produced fake Song rows from buttons/labels.
    SONG_ITEM_RE = re.compile(r"(?:^|\s)(?:song|track|music)-item(?:\s|$)", re.I)
    TRACK_NUMBER_RE = re.compile(r"(?:^|\s)(?:song|track)-number(?:\s|$)", re.I)
    DURATION_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")
    SONG_PAGE_HREF_RE = re.compile(r"/song/", re.I)
    AUDIO_FILE_HREF_RE = re.compile(r"\.(mp3|flac|wav|aac|m4a|ogg|wma|opus)(?:\?|$)", re.I)
    ZIP_HREF_RE = re.compile(
        r"(download-album|download-all|download\.zip|/zip$|\.zip(?:\?|$))", re.I
    )
    ZIP_TEXT_RE = re.compile(
        r"download\s*(?:all\s+songs|songs|album)?\s*(?:\(?zip\)?|zip)\s*$|\(zip\)", re.I
    )
    ARTIFACT_TITLE_RE = re.compile(
        r"^(?:download(?:\s+all(?:\s+songs)?|\s*zip)?|zip\s*download|track)\s*\d*$",
        re.I,
    )
    
    def __init__(self, config: CrawlerConfigSchema = None):
        self.config = config or CrawlerConfigSchema()
        self.engine_config = CrawlConfig(
            max_concurrency=self.config.max_concurrency,
            request_timeout=self.config.request_timeout,
            max_retries=self.config.max_retries,
            request_delay_ms=self.config.request_delay_ms,
            user_agent=self.config.user_agent,
            respect_robots_txt=self.config.respect_robots_txt,
            follow_redirects=self.config.follow_redirects
        )
        self.progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._stop_requested = False
        
    def set_progress_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for progress updates."""
        self.progress_callback = callback
    
    def _emit_progress(self, data: Dict[str, Any]):
        """Emit progress update."""
        if self.progress_callback:
            try:
                self.progress_callback(data)
            except Exception as e:
                logger.error("Progress callback error", error=str(e))
    
    def request_stop(self):
        """Request graceful stop."""
        self._stop_requested = True
    
    def generate_year_urls(self, base_url: str, start_year: int, end_year: int) -> List[tuple[int, str]]:
        """Generate URLs by replacing {year}, a trailing year, or appending one."""
        normalized_base_url = base_url.strip().rstrip("/")
        trailing_year_pattern = re.compile(r"/(?:19|20)\d{2}$")
        urls = []

        for year in range(start_year, end_year + 1):
            if "{year}" in normalized_base_url:
                url = normalized_base_url.format(year=year)
            elif trailing_year_pattern.search(normalized_base_url):
                url = trailing_year_pattern.sub(f"/{year}", normalized_base_url)
            else:
                url = f"{normalized_base_url}/{year}"
            urls.append((year, url))

        return urls
    
    async def crawl_year(
        self, 
        engine: CrawlerEngine,
        year: int, 
        url: str,
        job_id: int
    ) -> Dict[str, Any]:
        """Crawl all pages for a specific year."""
        logger.info("Crawling year", year=year, url=url, job_id=job_id)
        
        self._emit_progress({
            "type": "year_start",
            "job_id": job_id,
            "year": year,
            "url": url
        })
        
        result = {
            "year": year,
            "url": url,
            "pages": [],
            "albums": [],
            "errors": []
        }
        
        # Fetch first page
        page_num = 1
        current_url = url
        
        while not self._stop_requested:
            logger.info("Fetching page", year=year, page=page_num, url=current_url)
            
            self._emit_progress({
                "type": "page_start",
                "job_id": job_id,
                "year": year,
                "page": page_num,
                "url": current_url
            })
            
            crawl_result = await engine.fetch(current_url)
            
            if crawl_result.error or crawl_result.status_code != 200:
                error_msg = f"Failed to fetch page {page_num}: {crawl_result.error or crawl_result.status_code}"
                logger.error(error_msg, year=year, url=current_url)
                result["errors"].append({
                    "url": current_url,
                    "page": page_num,
                    "error": error_msg
                })
                break
            
            # Parse page
            soup = engine.parse_html(crawl_result.html)
            
            # Extract albums from this page
            albums = self._extract_albums(soup, current_url, year, page_num)
            result["pages"].append({
                "page": page_num,
                "url": current_url,
                "albums_found": len(albums)
            })
            result["albums"].extend(albums)
            
            self._emit_progress({
                "type": "page_complete",
                "job_id": job_id,
                "year": year,
                "page": page_num,
                "albums_found": len(albums),
                "total_albums": len(result["albums"])
            })
            
            # Find next page
            next_url = self._find_next_page(soup, current_url, page_num)
            if not next_url or next_url == current_url:
                logger.info("No more pages", year=year, last_page=page_num)
                break
            
            current_url = next_url
            page_num += 1
        
        self._emit_progress({
            "type": "year_complete",
            "job_id": job_id,
            "year": year,
            "total_pages": page_num,
            "total_albums": len(result["albums"])
        })
        
        return result
    
    def _extract_albums(
        self, 
        soup: BeautifulSoup, 
        base_url: str, 
        year: int,
        page_num: int
    ) -> List[AlbumInfo]:
        """Extract album links from a category page."""
        albums = []
        
        # Common patterns for album links
        # Pattern 1: Links containing "album" in URL
        for link in soup.find_all('a', href=re.compile(r'album', re.I)):
            href = link.get('href', '')
            if not href:
                continue
            
            full_url = urljoin(base_url, href)
            title = self._extract_text(link)
            
            # Try to find cover image
            cover = None
            parent = link.find_parent()
            if parent:
                img = parent.find('img')
                if img:
                    cover = img.get('src') or img.get('data-src')
                    if cover:
                        cover = urljoin(base_url, cover)
            
            album = AlbumInfo(
                title=title or "Unknown Album",
                url=full_url,
                year=year,
                category_url=base_url,
                discovery_page=page_num,
                cover_image=cover
            )
            albums.append(album)
        
        # Pattern 2: Look for album containers
        album_containers = soup.find_all(['div', 'article'], class_=re.compile(r'album|item|card', re.I))
        for container in album_containers:
            link = container.find('a', href=True)
            if not link:
                continue
            
            href = link.get('href', '')
            if 'album' not in href.lower():
                continue
            
            full_url = urljoin(base_url, href)
            
            # Check if already found
            if any(a.url == full_url for a in albums):
                continue
            
            title_elem = container.find(['h2', 'h3', 'h4', '.title', '.album-title'])
            title = self._extract_text(title_elem) or self._extract_text(link)
            
            cover_img = container.find('img')
            cover = None
            if cover_img:
                cover = cover_img.get('src') or cover_img.get('data-src')
                if cover:
                    cover = urljoin(base_url, cover)
            
            album = AlbumInfo(
                title=title or "Unknown Album",
                url=full_url,
                year=year,
                category_url=base_url,
                discovery_page=page_num,
                cover_image=cover
            )
            albums.append(album)
        
        # Remove duplicates by URL
        seen = set()
        unique_albums = []
        for album in albums:
            if album.url not in seen:
                seen.add(album.url)
                unique_albums.append(album)
        
        return unique_albums
    
    def _find_next_page(self, soup: BeautifulSoup, current_url: str, current_page: int) -> Optional[str]:
        """Find the URL of the next page."""
        # Pattern 1: Look for "next" link
        next_link = soup.find('a', text=re.compile(r'next|›|→|»', re.I))
        if next_link and next_link.get('href'):
            return urljoin(current_url, next_link['href'])
        
        # Pattern 2: Look for pagination with page numbers
        pagination = soup.find(['ul', 'div'], class_=re.compile(r'pagination|pages', re.I))
        if pagination:
            # Look for link to current_page + 1
            next_page_num = current_page + 1
            page_links = pagination.find_all('a', href=True)
            for link in page_links:
                text = self._extract_text(link)
                if text and str(next_page_num) in text:
                    return urljoin(current_url, link['href'])
        
        # Pattern 3: Look for numbered page links
        for link in soup.find_all('a', href=True):
            text = self._extract_text(link)
            if text and text.strip() == str(current_page + 1):
                return urljoin(current_url, link['href'])
        
        return None
    
    async def analyze_album(
        self, 
        engine: CrawlerEngine,
        album_url: str,
        job_id: int,
        album_title: str = ""
    ) -> Optional[AlbumDetails]:
        """Analyze an album page and extract all details."""
        logger.info("Analyzing album", url=album_url, job_id=job_id)
        
        self._emit_progress({
            "type": "album_start",
            "job_id": job_id,
            "album_url": album_url,
            "album_title": album_title
        })
        
        crawl_result = await engine.fetch(album_url)
        
        if crawl_result.error or crawl_result.status_code != 200:
            logger.error(
                "Failed to fetch album", 
                url=album_url, 
                error=crawl_result.error,
                status_code=crawl_result.status_code
            )
            return None
        
        soup = engine.parse_html(crawl_result.html)
        
        # Extract album metadata
        title = self._extract_album_title(soup) or album_title or "Unknown Album"
        artist = self._extract_artist(soup)
        music_director = self._extract_music_director(soup)
        genre = self._extract_genre(soup)
        description = self._extract_description(soup)
        cover_image = self._extract_cover_image(soup, album_url)
        release_year = self._extract_release_year(soup)
        
        # Look for ZIP download
        zip_url = self._extract_zip_url(soup, album_url)
        
        # Extract songs
        songs = self._extract_songs(soup, album_url)

        # Extract audio resources present directly on the album page
        audio_resources = self._extract_audio_resources(soup, album_url)

        # Individual song pages usually carry the real audio stream URLs,
        # so visit each discovered song and attach its resources.
        resources_found = len(audio_resources)
        for song in songs:
            song_resources = await self.analyze_song(engine, song, job_id)
            song.audio_resources = song_resources
            resources_found += len(song_resources)

        details = AlbumDetails(
            title=title,
            url=album_url,
            release_year=release_year,
            artist=artist,
            music_director=music_director,
            genre=genre,
            description=description,
            cover_image_url=cover_image,
            zip_url=zip_url,
            songs=songs,
            audio_resources=audio_resources
        )
        
        self._emit_progress({
            "type": "album_complete",
            "job_id": job_id,
            "album_url": album_url,
            "album_title": title,
            "songs_found": len(songs),
            "resources_found": resources_found,
            "has_zip": zip_url is not None
        })
        
        return details
    
    def _extract_album_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract album title from page."""
        # Try common selectors
        selectors = [
            'h1.album-title', 'h1.title', '.album-title h1',
            'h1', '.page-title', '.entry-title',
            '[class*="album"] h1', '[class*="title"] h1'
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return self._extract_text(elem)
        return None
    
    def _extract_artist(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract artist name."""
        patterns = [
            r'artist|singer|performer',
            r'by\s*:?\s*(.+)'
        ]
        
        for elem in soup.find_all(text=re.compile(r'artist|singer', re.I)):
            parent = elem.find_parent()
            if parent:
                text = self._extract_text(parent)
                match = re.search(r'(?:artist|singer)s?\s*:?\s*([^\n<]+)', text, re.I)
                if match:
                    return match.group(1).strip()
        return None
    
    def _extract_music_director(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract music director/composer."""
        for elem in soup.find_all(text=re.compile(r'composer|director|music', re.I)):
            parent = elem.find_parent()
            if parent:
                text = self._extract_text(parent)
                match = re.search(r'(?:music\s*(?:director|composer)|composer|director)\s*:?\s*([^\n<]+)', text, re.I)
                if match:
                    return match.group(1).strip()
        return None
    
    def _extract_genre(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract genre."""
        for elem in soup.find_all(text=re.compile(r'genre', re.I)):
            parent = elem.find_parent()
            if parent:
                text = self._extract_text(parent)
                match = re.search(r'genre\s*:?\s*([^\n<,]+)', text, re.I)
                if match:
                    return match.group(1).strip()
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract album description."""
        selectors = [
            '.description', '.album-description',
            '.summary', '.content',
            '[class*="desc"]', 'meta[name="description"]'
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                if elem.name == 'meta':
                    return elem.get('content')
                return self._extract_text(elem)
        return None
    
    def _extract_cover_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extract cover image URL."""
        selectors = [
            '.album-cover img', '.cover img',
            '.album-art img', '.artwork img',
            'img[class*="cover"]', 'img[class*="album"]'
        ]
        for selector in selectors:
            img = soup.select_one(selector)
            if img:
                src = img.get('src') or img.get('data-src')
                if src:
                    return urljoin(base_url, src)
        
        # Try meta tags
        meta_img = soup.find('meta', property='og:image')
        if meta_img:
            return urljoin(base_url, meta_img.get('content', ''))
        
        return None
    
    def _extract_release_year(self, soup: BeautifulSoup) -> Optional[int]:
        """Extract release year."""
        text = soup.get_text()
        # Look for 4-digit year between 1900-2030
        matches = re.findall(r'\b(19\d{2}|20\d{2}|2030)\b', text)
        if matches:
            return int(matches[0])
        return None
    
    def _extract_zip_url(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extract the album ZIP download URL (distinct from individual songs)."""
        # Pattern 1: dedicated "download all" buttons (e.g. btn-download-all
        # pointing at /download-album.php). These are the album ZIP links.
        for btn in soup.find_all(['a', 'button'], href=True):
            href = btn.get('href') or ''
            class_text = ' '.join(btn.get('class', []))
            text = self._extract_text(btn) or ''
            if self.ZIP_HREF_RE.search(href) and (
                'download' in class_text.lower() or 'zip' in text.lower()
                or 'download-all' in href.lower()
            ):
                return urljoin(base_url, href)
            if self.ZIP_TEXT_RE.search(text) and btn.name == 'a':
                return urljoin(base_url, href)

        # Pattern 2: generic text like "Download All Songs (ZIP)"
        zip_patterns = [
            r'download.*zip|zip.*download',
            r'download.*all|all.*songs.*download'
        ]

        for pattern in zip_patterns:
            for elem in soup.find_all(text=re.compile(pattern, re.I)):
                parent = elem.find_parent('a', href=True)
                if parent:
                    return urljoin(base_url, parent['href'])

        # Pattern 3: buttons with download class
        for btn in soup.find_all(['a', 'button'], class_=re.compile(r'download|zip', re.I)):
            href = btn.get('href')
            if href:
                candidate = urljoin(base_url, href)
                if self.ZIP_HREF_RE.search(candidate):
                    return candidate

        # Pattern 4: data attributes
        for elem in soup.find_all(attrs={'data-download': True}):
            return urljoin(base_url, elem['data-download'])

        return None
    
    def _is_zip_url(self, href: str) -> bool:
        """Return True when an href points at an album ZIP download."""
        return bool(self.ZIP_HREF_RE.search(href or ""))
    
    def _is_zip_element(self, element) -> bool:
        """Return True when an element is the album ZIP/download-all button."""
        text = self._extract_text(element) or ""
        if self.ZIP_TEXT_RE.search(text):
            return True
        for link in element.find_all('a', href=True):
            if self._is_zip_url(link.get('href', '')):
                return True
        return False
    
    def _is_artifact_title(self, title: Optional[str]) -> bool:
        """Return True when a title is a parser artifact (ZIP/download buttons)."""
        if not title:
            return True
        stripped = title.strip()
        if not stripped:
            return True
        if self.ARTIFACT_TITLE_RE.match(stripped) or "ZIP" in stripped.upper():
            return True
        return False
    
    def _extract_songs(self, soup: BeautifulSoup, base_url: str) -> List[SongInfo]:
        """Extract real song entries from an album page.

        Only dedicated song list rows are treated as songs. ZIP/download-all
        buttons and generic labels (track buttons, subscribe buttons, ...) are
        ignored so they never become fake Song records.
        """
        songs = []

        # Pattern 1: dedicated song list items (song-item / track-item / music-item)
        items = soup.find_all(['li', 'div', 'tr'], class_=self.SONG_ITEM_RE)
        for item in items:
            if self._is_zip_element(item):
                continue
            song = self._parse_song_item(item, base_url)
            if song:
                songs.append(song)

        # Pattern 2 (fallback): table rows when no dedicated song containers
        # are present. Rows whose cells look like ZIP/download buttons are
        # excluded by _is_artifact_title.
        if not songs:
            rows = soup.find_all('tr')
            for idx, row in enumerate(rows[1:], 1):  # Skip header
                if self._is_zip_element(row):
                    continue
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue
                title = self._extract_text(cells[0])
                if not title or self._is_artifact_title(title):
                    continue
                link = row.find('a', href=True)
                song_url = urljoin(base_url, link['href']) if link else None
                songs.append(SongInfo(
                    title=title,
                    url=song_url,
                    track_number=idx
                ))

        # De-duplicate: same song page URL (or same title) listed once
        unique: List[SongInfo] = []
        seen_urls = set()
        seen_titles = set()
        for song in songs:
            key = song.url if song.url else f"{song.title}:{song.track_number}"
            title_key = song.title.strip().lower()
            if key in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(key)
            seen_titles.add(title_key)
            unique.append(song)

        return unique
    
    def _parse_song_item(self, item, base_url: str) -> Optional[SongInfo]:
        """Parse a single song list item into SongInfo (or None for junk)."""
        link = item.find('a', href=self.SONG_PAGE_HREF_RE)
        if not link:
            # Fall back to the first non-download link inside the item
            for candidate in item.find_all('a', href=True):
                if self._is_zip_url(candidate.get('href', '')):
                    continue
                link = candidate
                break
        if not link:
            return None

        href = urljoin(base_url, link.get('href', ''))
        if self._is_zip_url(href):
            return None

        title = self._extract_text(link)
        title_el = item.find(['h3', 'h4', '.title', '.song-title'])
        if title_el:
            candidate = self._extract_text(title_el)
            if candidate and not self._is_artifact_title(candidate):
                title = candidate
        if self._is_artifact_title(title):
            return None

        # Track number
        track_number = None
        num_el = item.find(class_=self.TRACK_NUMBER_RE)
        if num_el:
            match = re.match(r"\s*(\d+)", self._extract_text(num_el) or "")
            if match:
                track_number = int(match.group(1))

        # Duration (e.g. "Duration: 03:01")
        duration = None
        for elem in item.find_all(['p', 'div', 'span'], class_=re.compile(
            r'song-meta|duration|length|time', re.I
        )):
            match = self.DURATION_RE.search(self._extract_text(elem) or "")
            if match:
                duration = match.group(1)
                break

        return SongInfo(
            title=title,
            url=href,
            track_number=track_number,
            duration=duration,
        )
    
    def _extract_song_page_resources(
        self, soup: BeautifulSoup, base_url: str
    ) -> List[AudioResourceInfo]:
        """Extract actual audio URLs from an individual song page."""
        resources = []

        # Pattern 1: <audio><source src="..."> stream URLs
        for audio in soup.find_all('audio'):
            for source in audio.find_all('source', src=True):
                resources.append(AudioResourceInfo(
                    url=urljoin(base_url, source.get('src', '')),
                    format=self._format_from_mime(source.get('type')),
                    bitrate=None,
                    file_size=None,
                ))
            src = audio.get('src')
            if isinstance(src, str) and src.strip():
                resources.append(AudioResourceInfo(
                    url=urljoin(base_url, src),
                    format=self._detect_format(src),
                    bitrate=None,
                    file_size=None,
                ))

        # Pattern 2: explicit audio file links (.mp3/.flac/...)
        for link in soup.find_all('a', href=self.AUDIO_FILE_HREF_RE):
            href = link['href']
            resources.append(AudioResourceInfo(
                url=urljoin(base_url, href),
                format=self._detect_format(href),
                bitrate=self._extract_bitrate(link),
                file_size=None,
            ))

        # Remove duplicates
        seen = set()
        unique = []
        for r in resources:
            if r.url not in seen:
                seen.add(r.url)
                unique.append(r)

        return unique
    
    @staticmethod
    def _format_from_mime(mime: Optional[str]) -> Optional[str]:
        """Map an audio MIME type to a storage format extension."""
        if not mime:
            return None
        match = re.search(r"audio/([\w+-]+)", mime)
        if not match:
            return None
        name = match.group(1).lower().replace("x-", "").replace("+", "")
        return {"mpeg": "mp3", "mp4": "m4a", "aac": "aac",
                "flac": "flac", "wav": "wav", "ogg": "ogg",
                "wma": "wma", "opus": "opus"}.get(name, name)
    
    async def analyze_song(
        self,
        engine: CrawlerEngine,
        song: SongInfo,
        job_id: int,
    ) -> List[AudioResourceInfo]:
        """Fetch an individual song page and extract its audio URLs.

        Many audio sites only expose the actual audio resource (stream URL or
        .mp3 link) on the per-song page rather than on the album page.
        """
        if not song.url:
            return []

        self._emit_progress({
            "type": "song_start",
            "job_id": job_id,
            "song_url": song.url,
            "song_title": song.title,
        })

        crawl_result = await engine.fetch(song.url)

        if crawl_result.error or crawl_result.status_code != 200:
            logger.warning(
                "Failed to fetch song page",
                url=song.url,
                error=crawl_result.error,
                status_code=crawl_result.status_code,
            )
            return []

        soup = engine.parse_html(crawl_result.html)
        resources = self._extract_song_page_resources(soup, song.url)

        self._emit_progress({
            "type": "song_complete",
            "job_id": job_id,
            "song_url": song.url,
            "song_title": song.title,
            "resources_found": len(resources),
        })

        return resources
    
    def _extract_audio_resources(self, soup: BeautifulSoup, base_url: str) -> List[AudioResourceInfo]:
        """Extract audio resource URLs directly present on the album page."""
        resources = []

        # Look for audio elements
        for audio in soup.find_all('audio'):
            src = audio.get('src') or audio.find('source', src=True)
            if src:
                if not isinstance(src, str):
                    src = src.get('src', '')
                if src:
                    resources.append(AudioResourceInfo(
                        url=urljoin(base_url, src),
                        format=self._detect_format(src),
                        bitrate=None,
                        file_size=None
                    ))

        # Look for download links
        for link in soup.find_all('a', href=re.compile(r'\.(mp3|flac|wav|aac|m4a|ogg)', re.I)):
            href = link['href']
            resources.append(AudioResourceInfo(
                url=urljoin(base_url, href),
                format=self._detect_format(href),
                bitrate=self._extract_bitrate(link),
                file_size=None
            ))

        # Remove duplicates
        seen = set()
        unique = []
        for r in resources:
            if r.url not in seen:
                seen.add(r.url)
                unique.append(r)

        return unique
    
    def _detect_format(self, url: str) -> Optional[str]:
        """Detect audio format from URL."""
        match = re.search(r'\.(mp3|flac|wav|aac|m4a|ogg|wma)(?:\?|$)', url, re.I)
        if match:
            return match.group(1).lower()
        return None
    
    def _extract_bitrate(self, element) -> Optional[str]:
        """Extract bitrate information."""
        text = self._extract_text(element)
        match = re.search(r'(\d+)\s*(kbps|kb|k)', text, re.I)
        if match:
            return f"{match.group(1)}kbps"
        return None
    
    def _extract_text(self, element) -> Optional[str]:
        """Safely extract text from element."""
        if not element:
            return None
        if hasattr(element, 'get_text'):
            return element.get_text(strip=True)
        if isinstance(element, str):
            return element.strip()
        return None
