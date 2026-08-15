"""Main FastAPI application for Audio Collection Analyzer."""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import structlog

from app.database.config import init_db
from app.api.routes import router
from app.storage.audio_storage import AudioStorage

load_dotenv()

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting up Audio Collection Analyzer API")

    # Initialize database (metadata only — audio lives on the filesystem)
    await init_db()
    logger.info("Database initialized")

    # Ensure filesystem directories exist
    storage = AudioStorage()
    storage.root.mkdir(parents=True, exist_ok=True)
    os.makedirs(os.getenv("ARCHIVE_DIR", "./archives"), exist_ok=True)
    os.makedirs(os.getenv("TEMP_DIR", "./temp"), exist_ok=True)
    logger.info("Audio storage ready", root=str(storage.root))

    yield

    # Shutdown
    logger.info("Shutting down Audio Collection Analyzer API")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Audio Collection Analyzer API",
        description="API for analyzing audio websites and managing authorized downloads",
        version="1.0.0",
        lifespan=lifespan
    )

    # CORS middleware
    allowed_origins = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(router, prefix="/api")

    # Static files for archives (filesystem, safe directory)
    archive_dir = os.getenv("ARCHIVE_DIR", "./archives")
    if os.path.isdir(archive_dir):
        app.mount("/archives", StaticFiles(directory=archive_dir), name="archives")

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "audio-analyzer-api"}

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        """Global exception handler."""
        logger.error("Unhandled exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "message": str(exc)}
        )

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("DEBUG", "false").lower() == "true"

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
