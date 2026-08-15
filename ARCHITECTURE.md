# Audio Collection Analyzer - Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐ │
│  │   Next.js Frontend  │    │   React Dashboard   │    │   WebSocket     │ │
│  │   (Port 3000)       │◄──►│   Components        │◄──►│   Real-time     │ │
│  └─────────────────────┘    └─────────────────────┘    └─────────────────┘ │
│           │                                                            │    │
│           │ HTTP/REST                                            WebSocket│    │
│           │                                                            │    │
└───────────┼────────────────────────────────────────────────────────────┼────┘
            │                                                            │
            ▼                                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API LAYER                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                           FastAPI Application                                │
│                              (Port 8000)                                     │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   ││
│  │  │  /analyze   │  │  /years     │  │  /albums    │  │  /download  │   ││
│  │  │  /jobs      │  │  /songs     │  │  /search    │  │  /archives  │   ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│           │                    │                    │                       │
└───────────┼────────────────────┼────────────────────┼───────────────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SERVICE LAYER                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐  │
│  │   CrawlService      │    │   DownloadService   │    │   SearchService │  │
│  │                     │    │                     │    │                 │  │
│  │  - Job Management   │    │  - Download Queue   │    │  - Full-text    │  │
│  │  - Progress Track   │    │  - File Organize    │    │  - Filtering    │  │
│  │  - State Machine    │    │  - ZIP Generation   │    │  - Ranking      │  │
│  └─────────────────────┘    └─────────────────────┘    └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CRAWLER LAYER                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     AudioWebsiteCrawler                                  ││
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  ││
│  │  │  Year Crawler   │  │  Album Crawler  │  │   Resource Crawler      │  ││
│  │  │                 │  │                 │  │                         │  ││
│  │  │  - URL Gen      │  │  - Metadata     │  │  - Audio URL Detection  │  ││
│  │  │  - Pagination   │  │  - Song List    │  │  - ZIP Detection        │  ││
│  │  │  - Link Extract │  │  - Cover Art    │  │  - Format/Bitrate       │  ││
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│           │                                                                 │
│           │ Async HTTP Requests                                              │
│           │ (httpx + asyncio)                                               │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                    CrawlerEngine                                         ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    ││
│  │  │Rate Limiter │  │   Retry     │  │   Parser    │  │   Queue     │    ││
│  │  │   (Token    │  │  (Exp.      │  │(Beautiful  │  │  (Async     │    ││
│  │  │   Bucket)   │  │   Backoff)  │  │   Soup)     │  │   Semaphore)│    ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
            │
            │ Binary Downloads
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       DOWNLOADER LAYER                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐  │
│  │   DownloadManager   │    │  ArchiveGenerator   │    │   FileStore     │  │
│  │                     │    │                     │    │                 │  │
│  │  - Concurrent DL    │    │  - ZIP Creation     │    │  - Organize     │  │
│  │  - Progress Track   │    │  - Directory Struct │    │  - Year/Album   │  │
│  │  - Resume Support   │    │  - Multi-year       │    │  - Deduplicate  │  │
│  └─────────────────────┘    └─────────────────────┘    └─────────────────┘  │
│           │                                                                 │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  downloads/                                                             ││
│  │  ├── 1990/                                                              ││
│  │  │   ├── Album 1/                                                       ││
│  │  │   │   ├── Song 1.mp3                                                 ││
│  │  │   │   └── Song 2.mp3                                                 ││
│  │  │   └── Album 2/                                                       ││
│  │  ├── 1991/                                                              ││
│  │  └── ...                                                                ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
            │
            │ SQL Queries
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                              PostgreSQL                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                                                                         ││
│  │   ┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐ ││
│  │   │  crawl_   │────►│  years    │────►│ categories│────►│  albums   │ ││
│  │   │   jobs    │     │           │     │           │     │           │ ││
│  │   └───────────┘     └───────────┘     └───────────┘     └─────┬─────┘ ││
│  │                                                                │       ││
│  │   ┌───────────┐     ┌───────────┐     ┌───────────┐           │       ││
│  │   │  archives │◄────│ download_ │     │   songs   │◄──────────┘       ││
│  │   │           │     │   jobs    │     │           │                   ││
│  │   └───────────┘     └───────────┘     └─────┬─────┘                   ││
│  │                                              │                         ││
│  │   ┌───────────┐     ┌───────────┐          │                         ││
│  │   │failed_urls│     │crawl_logs │     ┌────┴───────┐                 ││
│  │   │           │     │           │     │   audio_   │                 ││
│  │   └───────────┘     └───────────┘     │  resources │                 ││
│  │                                       └────────────┘                 ││
│  │                                                                       ││
│  └───────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Analysis Flow

```
User Input (URL, Years)
    │
    ▼
┌─────────────────┐
│  CrawlService   │
│  - Create Job   │
│  - Validate     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│   AudioWebsiteCrawler   │
│   - Generate Year URLs  │
│   - For each year:      │
│     - Fetch pages       │
│     - Extract albums    │
│     - Analyze albums    │
│     - Extract songs     │
│     - Find resources    │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│      Database Store     │
│   - Years, Albums, etc  │
└─────────────────────────┘
```

### 2. Download Flow

```
User Request (Year/Album/Song)
    │
    ▼
┌─────────────────┐
│ DownloadService │
│  - Create Job   │
│  - Query DB     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│    DownloadManager      │
│   - Collect resources   │
│   - Queue downloads     │
│   - Progress updates    │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│   ArchiveGenerator      │
│   - Organize files      │
│   - Create ZIP          │
│   - Store archive       │
└─────────────────────────┘
```

## Component Details

### CrawlerEngine
- **RateLimiter**: Token bucket algorithm per domain
- **Retry Logic**: Exponential backoff with jitter
- **Parser**: BeautifulSoup4 with lxml
- **Queue**: Asyncio semaphore for concurrency control

### AudioWebsiteCrawler
- **URL Generation**: Dynamic year-based URL generation
- **Pagination Detection**: Automatic next-page discovery
- **Album Extraction**: Multiple pattern matching strategies
- **Metadata Extraction**: Title, artist, director, genre, cover art
- **Resource Detection**: Audio URLs, ZIP links, formats

### DownloadManager
- **Concurrent Downloads**: Configurable parallelism
- **Progress Tracking**: Byte-level progress with callbacks
- **Resume Support**: Partial download continuation
- **File Organization**: Year/Album directory structure

### ArchiveGenerator
- **ZIP Creation**: Streaming ZIP for large collections
- **Directory Structure**: Organized by year and album
- **Multi-year Support**: Combine multiple years in one archive

## Database Schema Relationships

```
CrawlJob (1)
  │
  ├──► Year (N)
  │      │
  │      ├──► Category (N)
  │             │
  │             ├──► Album (N)
  │                    │
  │                    ├──► Song (N)
  │                           │
  │                           ├──► AudioResource (N)
  │
  ├──► CrawlLog (N)
  │
  └──► FailedUrl (N)

DownloadJob (1)
  │
  ├──► Archive (1)
  │
  └──► References: Year, Album, Song
```

## Concurrency Model

```
┌─────────────────────────────────────────────┐
│           Asyncio Event Loop                │
├─────────────────────────────────────────────┤
│                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐     │
│  │  Task 1 │  │  Task 2 │  │  Task N │     │
│  │ (Year   │  │ (Year   │  │ (Year   │     │
│  │ Crawl)  │  │ Crawl)  │  │ Crawl)  │     │
│  └────┬────┘  └────┬────┘  └────┬────┘     │
│       │            │            │           │
│       └────────────┴────────────┘           │
│                    │                        │
│              Semaphore (max_concurrency)    │
│                    │                        │
│       ┌────────────┼────────────┐           │
│       ▼            ▼            ▼           │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐     │
│  │  HTTP   │  │  HTTP   │  │  HTTP   │     │
│  │ Request │  │ Request │  │ Request │     │
│  │ (Rate   │  │ (Rate   │  │ (Rate   │     │
│  │Limited) │  │Limited) │  │Limited) │     │
│  └─────────┘  └─────────┘  └─────────┘     │
│                                             │
└─────────────────────────────────────────────┘
```

## Security Considerations

1. **Authorization Only**: Only downloads when user has permission
2. **Rate Limiting**: Respects target server capacity
3. **robots.txt**: Respects crawling restrictions
4. **No Bypass**: Doesn't circumvent protections

## Scalability

- **Horizontal**: Multiple crawler instances
- **Vertical**: Configurable concurrency
- **Database**: Connection pooling
- **Storage**: External volume mounts
