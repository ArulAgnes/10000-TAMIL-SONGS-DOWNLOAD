# Audio Collection Analyzer

A complete production-quality full-stack application for analyzing audio websites and organizing publicly exposed audio resources by year.

## Features

- **Year-Based Crawling**: Automatically discover and analyze audio collections organized by year (1990-2026)
- **Pagination Detection**: Automatically detect and navigate through category page pagination
- **Album Discovery**: Extract album metadata including title, artist, music director, genre
- **Song Analysis**: Identify individual songs with track information
- **Audio Resource Detection**: Find authorized audio URLs with format and bitrate information
- **ZIP Download Support**: Detect and record official ZIP download links
- **Progress Tracking**: Real-time progress updates via WebSocket
- **Download Management**: Download authorized audio resources with proper organization
- **Archive Generation**: Create well-organized ZIP archives by year and album
- **Search Functionality**: Search across songs, albums, and artists
- **Statistics Dashboard**: View comprehensive collection statistics

## Architecture

### Backend (Python/FastAPI)
- **Crawler Engine**: Asynchronous web crawler with rate limiting and retry logic
- **Audio Crawler**: Specialized crawler for year-based audio websites
- **Download Manager**: Manage authorized downloads with progress tracking
- **Archive Generator**: Create organized ZIP archives
- **Database**: PostgreSQL with SQLAlchemy ORM

### Frontend (Next.js/TypeScript)
- **Dashboard**: Modern React-based dashboard with Tailwind CSS
- **Real-time Updates**: WebSocket integration for live progress
- **Year Selection**: Interactive year cards with statistics
- **Download Interface**: Easy download management for years and albums

## Project Structure

```
audio-collection-analyzer/
├── backend/
│   ├── app/
│   │   ├── api/           # API routes
│   │   ├── crawler/       # Crawler engine and audio crawler
│   │   ├── downloader/    # Download manager
│   │   ├── archive/       # ZIP archive generator
│   │   ├── database/      # Database configuration
│   │   ├── models/        # SQLAlchemy models and Pydantic schemas
│   │   ├── services/      # Business logic services
│   │   └── main.py        # FastAPI application
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/               # Next.js app router
│   ├── components/        # React components
│   ├── lib/               # API client and utilities
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
└── README.md
```

## Quick Start

### Using Docker Compose

1. Clone the repository:
```bash
git clone <repository-url>
cd audio-collection-analyzer
```

2. Create environment files:
```bash
cd
cp frontend/.env.example frontend/.env.local
```

3. Start all services:
```bash
docker-compose up -d
```

4. Access the application:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

### Manual Setup

#### Backend

1. Create virtual environment:
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up PostgreSQL database and update `.env`

4. Run the backend:
```bash
python -m app.main
```

#### Frontend

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Run the development server:
```bash
npm run dev
```

## Usage

### Starting an Analysis

1. Open the dashboard at http://localhost:3000
2. Enter the website URL pattern with `{year}` placeholder
   - Example: `https://example.com/category/songs/{year}`
3. Set start and end years (e.g., 1990 to 2026)
4. Configure advanced options if needed
5. Click "Analyze Collection"

### Downloading Collections

1. Click on a year card to view details
2. Click "Download Year Collection" to download all songs for that year
3. Or use the API to download specific albums or songs

### API Endpoints

#### Analysis
- `POST /api/analyze` - Start a new analysis job
- `GET /api/jobs/{id}` - Get job status and progress
- `POST /api/jobs/{id}/stop` - Stop a running job

#### Data
- `GET /api/years` - List all discovered years
- `GET /api/albums` - List albums with filtering
- `GET /api/songs` - List songs with filtering

#### Downloads
- `POST /api/download/song` - Download a single song
- `POST /api/download/album` - Download an album
- `POST /api/download/year` - Download a year collection
- `POST /api/download/years` - Download multiple years

#### Search & Statistics
- `POST /api/search` - Search across collections
- `GET /api/statistics` - Get dashboard statistics

## Configuration

### Environment Variables

#### Backend
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/audio_analyzer
REDIS_URL=redis://localhost:6379/0
MAX_CONCURRENCY=5
REQUEST_TIMEOUT=30
MAX_RETRIES=3
REQUEST_DELAY_MS=500
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=true
```

#### Frontend
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Crawler Configuration

The crawler supports the following configuration options:

- `max_concurrency`: Maximum concurrent requests (1-20)
- `request_timeout`: Request timeout in seconds (5-120)
- `max_retries`: Maximum retry attempts (0-10)
- `request_delay_ms`: Delay between requests in milliseconds (0-5000)
- `user_agent`: Custom User-Agent string
- `respect_robots_txt`: Respect robots.txt (default: true)

## Important Notes

- **Authorization Required**: This tool only downloads audio files when the user has authorization to download/reproduce them
- **No Bypassing**: The application does not bypass authentication, DRM, paywalls, hotlink protection, CAPTCHA, or robots.txt restrictions
- **Rate Limiting**: Built-in rate limiting prevents overwhelming target servers
- **Respectful Crawling**: Configurable delays and concurrency limits ensure respectful crawling

## Database Schema

### Tables
- `crawl_jobs` - Analysis job tracking
- `years` - Discovered years
- `categories` - Category pages
- `albums` - Discovered albums
- `songs` - Songs within albums
- `audio_resources` - Authorized audio file URLs
- `download_jobs` - Download job tracking
- `archives` - Generated ZIP archives
- `crawl_logs` - Crawl activity logs
- `failed_urls` - Failed URL tracking

## Development

### Running Tests

```bash
cd backend
pytest
```

### Database Migrations

```bash
cd backend
# Generate migration
alembic revision --autogenerate -m "Description"

# Apply migration
alembic upgrade head
```

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please read CONTRIBUTING.md for guidelines.
