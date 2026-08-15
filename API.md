# Audio Collection Analyzer API Documentation

## Base URL
```
http://localhost:8000/api
```

## WebSocket
```
ws://localhost:8000/api/ws/progress/{job_id}
```

## Endpoints

### Analysis

#### Start Analysis
```http
POST /analyze
```

Request body:
```json
{
  "base_url": "https://example.com/category/songs/{year}",
  "start_year": 1990,
  "end_year": 2026,
  "config": {
    "max_concurrency": 5,
    "request_timeout": 30,
    "max_retries": 3,
    "request_delay_ms": 500
  }
}
```

Response:
```json
{
  "job_id": 1,
  "status": "running",
  "message": "Analysis started successfully",
  "base_url": "https://example.com/category/songs/{year}",
  "start_year": 1990,
  "end_year": 2026,
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### Get Job Status
```http
GET /jobs/{job_id}
```

Response:
```json
{
  "job_id": 1,
  "status": "running",
  "total_years": 37,
  "processed_years": 15,
  "year_progress": 40.5,
  "total_pages": 156,
  "processed_pages": 89,
  "page_progress": 57.1,
  "total_albums": 420,
  "processed_albums": 183,
  "album_progress": 43.6,
  "total_songs": 1250,
  "processed_songs": 521,
  "song_progress": 41.7,
  "overall_progress": 45.2,
  "current_year": 2011,
  "current_page": 3,
  "current_album": "Album Name",
  "started_at": "2024-01-15T10:30:00Z"
}
```

#### Stop Job
```http
POST /jobs/{job_id}/stop
```

### Years

#### List Years
```http
GET /years?job_id={job_id}
```

Response:
```json
[
  {
    "id": 1,
    "year": 2026,
    "url": "https://example.com/category/songs/2026",
    "status": "completed",
    "total_pages": 9,
    "total_albums": 211,
    "total_songs": 590,
    "created_at": "2024-01-15T10:30:00Z",
    "completed_at": "2024-01-15T10:35:00Z"
  }
]
```

#### Get Year Details
```http
GET /years/{year_id}
```

### Albums

#### List Albums
```http
GET /albums?year_id={year_id}&search={query}&limit=20&offset=0
```

Response:
```json
[
  {
    "id": 1,
    "title": "Album Name",
    "url": "https://example.com/album/123",
    "release_year": 2026,
    "artist": "Artist Name",
    "music_director": "Director Name",
    "genre": "Pop",
    "description": "Album description",
    "cover_image_url": "https://example.com/cover.jpg",
    "zip_url": "https://example.com/download.zip",
    "zip_status": "available",
    "status": "completed"
  }
]
```

#### Get Album Details
```http
GET /albums/{album_id}
```

### Songs

#### List Songs
```http
GET /songs?album_id={album_id}&search={query}&limit=20&offset=0
```

Response:
```json
[
  {
    "id": 1,
    "title": "Song Name",
    "track_number": 1,
    "duration": "3:45",
    "artist": "Artist Name",
    "status": "completed"
  }
]
```

#### Get Song Details
```http
GET /songs/{song_id}
```

### Downloads

#### Download Song
```http
POST /download/song
```

Request body:
```json
{
  "song_id": 1
}
```

#### Download Album
```http
POST /download/album
```

Request body:
```json
{
  "album_id": 1
}
```

#### Download Year
```http
POST /download/year
```

Request body:
```json
{
  "year_id": 1
}
```

#### Download Multiple Years
```http
POST /download/years
```

Request body:
```json
{
  "start_year": 1990,
  "end_year": 2026
}
```

#### Get Download Progress
```http
GET /download/{job_id}/progress
```

Response:
```json
{
  "job_id": 1,
  "status": "running",
  "total_files": 100,
  "downloaded_files": 45,
  "failed_files": 2,
  "total_size_bytes": 104857600,
  "downloaded_size_bytes": 47185920,
  "progress_percentage": 45.0,
  "current_file": "song.mp3",
  "speed_mbps": 2.5,
  "eta_seconds": 120
}
```

#### Cancel Download
```http
POST /download/{job_id}/cancel
```

### Archives

#### List Archives
```http
GET /archives?limit=20&offset=0
```

Response:
```json
[
  {
    "id": 1,
    "download_job_id": 1,
    "name": "Audio_Collection_2026_20240115_103000.zip",
    "path": "/archives/Audio_Collection_2026_20240115_103000.zip",
    "size_bytes": 104857600,
    "file_count": 100,
    "year_start": 2026,
    "year_end": 2026,
    "created_at": "2024-01-15T10:30:00Z",
    "download_url": "/api/archives/1/file"
  }
]
```

#### Get Archive
```http
GET /archive/{archive_id}
```

### Search

#### Search
```http
POST /search
```

Request body:
```json
{
  "query": "song name",
  "search_type": "all",
  "year": 2026,
  "limit": 20,
  "offset": 0
}
```

Response:
```json
{
  "query": "song name",
  "total_results": 15,
  "results": [
    {
      "type": "song",
      "id": 1,
      "title": "Song Name",
      "subtitle": "Album Name",
      "year": 2026,
      "url": "https://example.com/song/1",
      "status": "available",
      "relevance_score": 0.95
    }
  ],
  "limit": 20,
  "offset": 0
}
```

### Statistics

#### Get Statistics
```http
GET /statistics
```

Response:
```json
{
  "overview": {
    "total_crawl_jobs": 5,
    "total_years": 37,
    "total_albums": 420,
    "total_songs": 1250,
    "total_audio_resources": 1500,
    "total_downloaded": 800,
    "total_failed": 50,
    "storage_used_bytes": 10737418240
  },
  "year_stats": [
    {
      "year": 2026,
      "albums_count": 211,
      "songs_count": 590,
      "resources_count": 620,
      "downloaded_count": 400,
      "failed_count": 20
    }
  ],
  "recent_jobs": [
    {
      "id": 1,
      "base_url": "https://example.com/category/songs/{year}",
      "status": "completed",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error message"
}
```

Common HTTP status codes:
- `400` - Bad Request
- `404` - Not Found
- `422` - Validation Error
- `500` - Internal Server Error

## WebSocket Protocol

Connect to the WebSocket endpoint to receive real-time progress updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/api/ws/progress/1');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.type, data);
};
```

Message types:
- `year_start` - Started crawling a year
- `page_start` - Started crawling a page
- `page_complete` - Completed crawling a page
- `year_complete` - Completed crawling a year
- `album_start` - Started analyzing an album
- `album_complete` - Completed analyzing an album
- `download_progress` - Download progress update
- `download_complete` - Download completed
- `archive_progress` - Archive creation progress
- `archive_complete` - Archive creation completed
