// API client — calls local Next.js API routes

export interface CrawlerConfig {
  max_concurrency?: number;
  request_timeout?: number;
  max_retries?: number;
  request_delay_ms?: number;
}

export interface AnalyzeRequest {
  base_url: string;
  start_year: number;
  end_year: number;
  config?: CrawlerConfig;
}

export interface AnalyzeResponse {
  job_id: number;
  status: string;
  message: string;
  base_url: string;
  start_year: number;
  end_year: number;
}

export interface CrawlProgress {
  job_id: number;
  status: string;
  total_years: number;
  processed_years: number;
  year_progress: number;
  total_pages: number;
  processed_pages: number;
  page_progress: number;
  total_albums: number;
  processed_albums: number;
  album_progress: number;
  total_songs: number;
  processed_songs: number;
  song_progress: number;
  overall_progress: number;
  current_year?: number;
  current_page?: number;
  current_album?: string;
  current_song?: string;
  current_activity?: string;
  error?: string;
}

export interface YearData {
  id: number;
  year: number;
  url: string;
  status: string;
  total_pages: number;
  total_albums: number;
  total_songs: number;
  created_at: string;
  completed_at?: string;
}

export interface AlbumData {
  id: number;
  title: string;
  url: string;
  release_year?: number;
  artist?: string;
  music_director?: string;
  description?: string;
  cover_image_url?: string;
  zip_url?: string;
  zip_status: string;
  status: string;
  songs?: SongData[];
}

export interface SongData {
  id: number;
  title: string;
  track_number?: number;
  duration?: string;
  duration_seconds?: number;
  artist?: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Artists
// ---------------------------------------------------------------------------

export interface ArtistData {
  id: number;
  name: string;
  normalized_name: string;
  slug: string;
  artist_type?: string | null;
  source_url?: string | null;
  song_count: number;
  first_seen?: string | null;
  last_seen?: string | null;
  created_at?: string | null;
}

export interface ArtistListResponse {
  total: number;
  limit: number;
  offset: number;
  artists: ArtistData[];
}

export interface ArtistSongData {
  id: number;
  title: string;
  album?: string | null;
  album_id?: number | null;
  year?: number | null;
  duration?: string | null;
  duration_seconds?: number | null;
  artist?: string | null;
  track_number?: number | null;
  status?: string | null;
  resource_count: number;
  source_url?: string | null;
}

export interface ArtistSongsResponse {
  artist: ArtistData;
  total: number;
  limit: number;
  offset: number;
  songs: ArtistSongData[];
}

export interface ArtistAnalyzeRequest {
  artist_id: number;
  artist_url?: string;
}

// ---------------------------------------------------------------------------
// Multi-year collections
// ---------------------------------------------------------------------------

export interface CollectionCreateRequest {
  base_url: string;
  start_year: number;
  end_year: number;
  archive_prefix?: string;
  config?: CrawlerConfig;
}

export interface CollectionResponse {
  job_id: number;
  status: string;
  years: number[];
  start_year: number;
  end_year: number;
  base_url: string;
  message: string;
  created_at: string;
}

export interface CollectionProgress {
  job_id: number;
  status: string;
  total_years: number;
  completed_years: number;
  total_albums: number;
  total_songs: number;
  total_resources: number;
  failed_urls: number;
  skipped_urls: number;
  current_year?: number | null;
  current_album?: string | null;
  current_song?: string | null;
  progress_percentage: number;
  started_at?: string | null;
  completed_at?: string | null;
  elapsed_seconds?: number | null;
  estimated_remaining_seconds?: number | null;
  error_message?: string | null;
}

export interface CollectionStatus {
  job_id: number;
  status: string;
  start_year: number;
  end_year: number;
  base_url: string;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface ArchiveData {
  id: number;
  download_job_id: number;
  crawl_job_id?: number | null;
  archive_type?: string | null;
  name: string;
  path: string;
  size_bytes: number;
  file_count: number;
  year_start?: number | null;
  year_end?: number | null;
  status?: string | null;
  error_message?: string | null;
  completed_at?: string | null;
  created_at: string;
  download_url?: string | null;
}

// Duration formatting: MM:SS / HH:MM:SS / "--:--"
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return "--:--";
  const s = Math.floor(seconds);
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const secs = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (hours > 0) return `${hours}:${pad(minutes)}:${pad(secs)}`;
  return `${pad(minutes)}:${pad(secs)}`;
}

export interface DownloadResponse {
  job_id: number;
  status: string;
  message: string;
  estimated_files: number;
}

export interface DownloadProgress {
  job_id: number;
  status: string;
  total_files: number;
  downloaded_files: number;
  progress_percentage: number;
  error?: string;
}

export interface ArchiveData {
  id: number;
  download_job_id: number;
  name: string;
  path: string;
  size_bytes: number;
  file_count: number;
  created_at: string;
}

export interface SearchResult {
  type: string;
  id: number;
  title: string;
  subtitle?: string;
  year?: number;
  status?: string;
  relevance_score: number;
}

export interface StatisticsOverview {
  total_crawl_jobs: number;
  total_years: number;
  total_albums: number;
  total_songs: number;
  total_audio_resources: number;
  total_downloaded: number;
  total_failed: number;
  storage_used_bytes: number;
}

export interface RecentJob {
  id: number;
  base_url: string;
  status: string;
  created_at: string;
}

export interface DashboardStatistics {
  overview: StatisticsOverview;
  year_stats: { year: number; albums_count: number; songs_count: number; resources_count: number; downloaded_count: number; failed_count: number; }[];
  recent_jobs: RecentJob[];
}

function extractDetail(payload: unknown): string {
  let detail: unknown = null;
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    if ("detail" in record) detail = record.detail;
    else if ("message" in record) detail = record.message;
  }

  const parts: string[] = [];
  const append = (value: unknown, prefix = ""): void => {
    if (typeof value === "string") {
      if (value.trim()) parts.push(prefix + value);
    } else if (Array.isArray(value)) {
      value.forEach((item) => append(item, prefix));
    } else if (value !== null && typeof value === "object") {
      const text = JSON.stringify(value);
      if (text && text !== "{}") parts.push(prefix + text);
    } else if (value !== null && value !== undefined && value !== "") {
      parts.push(prefix + String(value));
    }
  };

  append(detail);
  if (parts.length === 0) append(payload);

  if (parts.length === 0) return "Request failed";
  return parts.join("; ");
}

class ApiClient {
  private async fetchJson<T>(endpoint: string, options?: RequestInit): Promise<T> {
    let res: Response;
    try {
      res = await fetch(endpoint, {
        ...options,
        headers: { "Content-Type": "application/json", ...options?.headers },
      });
    } catch (err) {
      throw new Error(
        `API request failed for ${endpoint}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }

    const text = await res.text();
    let payload: unknown = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = text;
    }

    if (!res.ok) {
      throw new Error(`API error ${res.status} ${endpoint}: ${extractDetail(payload)}`);
    }

    return payload as T;
  }

  async startAnalysis(req: AnalyzeRequest): Promise<AnalyzeResponse> {
    return this.fetchJson("/api/analyze", { method: "POST", body: JSON.stringify(req) });
  }

  async getJobStatus(jobId: number): Promise<CrawlProgress> {
    return this.fetchJson(`/api/jobs/${jobId}`);
  }

  async stopJob(jobId: number): Promise<void> {
    await this.fetchJson(`/api/jobs/${jobId}/stop`, { method: "POST" });
  }

  async getYears(jobId?: number): Promise<YearData[]> {
    const params = jobId ? `?job_id=${jobId}` : "";
    return this.fetchJson(`/api/years${params}`);
  }

  async getAlbums(params?: { year_id?: number; search?: string; limit?: number }): Promise<AlbumData[]> {
    const sp = new URLSearchParams();
    if (params?.year_id) sp.set("year_id", String(params.year_id));
    if (params?.search) sp.set("search", params.search);
    if (params?.limit) sp.set("limit", String(params.limit));
    return this.fetchJson(`/api/albums?${sp}`);
  }

  async getAlbum(albumId: number): Promise<AlbumData> {
    return this.fetchJson(`/api/albums/${albumId}`);
  }

  async getSongs(params?: { album_id?: number; search?: string }): Promise<SongData[]> {
    const sp = new URLSearchParams();
    if (params?.album_id) sp.set("album_id", String(params.album_id));
    if (params?.search) sp.set("search", params.search);
    return this.fetchJson(`/api/songs?${sp}`);
  }

  async downloadYear(yearId: number): Promise<DownloadResponse> {
    return this.fetchJson("/api/download/year", {
      method: "POST",
      body: JSON.stringify({ year_id: yearId }),
    });
  }

  async getDownloadProgress(jobId: number): Promise<DownloadProgress> {
    return this.fetchJson(`/api/download/${jobId}`);
  }

  async getArchives(): Promise<ArchiveData[]> {
    return this.fetchJson("/api/archives");
  }

  async getArtists(params?: {
    letter?: string;
    search?: string;
    sort?: string;
    limit?: number;
    offset?: number;
  }): Promise<ArtistListResponse> {
    const sp = new URLSearchParams();
    if (params?.letter) sp.set("letter", params.letter);
    if (params?.search) sp.set("search", params.search);
    if (params?.sort) sp.set("sort", params.sort);
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.offset) sp.set("offset", String(params.offset));
    return this.fetchJson(`/api/artists?${sp}`);
  }

  async searchArtists(q: string, limit = 10): Promise<ArtistListResponse> {
    const sp = new URLSearchParams();
    sp.set("q", q);
    sp.set("limit", String(limit));
    return this.fetchJson(`/api/artists/search?${sp}`);
  }

  async getArtist(slug: string): Promise<ArtistData> {
    return this.fetchJson(`/api/artists/${slug}`);
  }

  async getArtistSongs(
    slug: string,
    params?: { year?: number; limit?: number; offset?: number },
  ): Promise<ArtistSongsResponse> {
    const sp = new URLSearchParams();
    if (params?.year) sp.set("year", String(params.year));
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.offset) sp.set("offset", String(params.offset));
    return this.fetchJson(`/api/artists/${slug}/songs?${sp}`);
  }

  async getArtistYears(slug: string): Promise<number[]> {
    return this.fetchJson(`/api/artists/${slug}/years`);
  }

  async analyzeArtist(req: ArtistAnalyzeRequest): Promise<{ status: string; message: string }> {
    return this.fetchJson("/api/artists/analyze", {
      method: "POST",
      body: JSON.stringify(req),
    });
  }

  async discoverArtists(indexUrl: string, artistType = "ARTIST", maxArtists = 2000) {
    return this.fetchJson("/api/artists/discover", {
      method: "POST",
      body: JSON.stringify({
        index_url: indexUrl,
        artist_type: artistType,
        max_artists: maxArtists,
      }),
    });
  }

  async createCollection(req: CollectionCreateRequest): Promise<CollectionResponse> {
    return this.fetchJson("/api/collections", {
      method: "POST",
      body: JSON.stringify(req),
    });
  }

  async getCollection(jobId: number): Promise<CollectionStatus> {
    return this.fetchJson(`/api/collections/${jobId}`);
  }

  async getCollectionProgress(jobId: number): Promise<CollectionProgress> {
    return this.fetchJson(`/api/collections/${jobId}/progress`);
  }

  async cancelCollection(jobId: number): Promise<{ cancelled: boolean; status: string }> {
    return this.fetchJson(`/api/collections/${jobId}/cancel`, { method: "POST" });
  }

  async createCollectionArchive(
    jobId: number,
    req: { prefix?: string; start_year?: number; end_year?: number },
  ): Promise<ArchiveData> {
    return this.fetchJson(`/api/collections/${jobId}/archive`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  }

  async getCollectionArchive(jobId: number): Promise<ArchiveData> {
    return this.fetchJson(`/api/collections/${jobId}/archive`);
  }

  async cancelCollectionArchive(jobId: number): Promise<{ cancelled: boolean; status: string }> {
    return this.fetchJson(`/api/collections/${jobId}/archive/cancel`, { method: "POST" });
  }

  async search(query: string, type?: string, year?: number): Promise<SearchResult[]> {
    return this.fetchJson("/api/search", {
      method: "POST",
      body: JSON.stringify({ query, search_type: type || "all", year }),
    });
  }

  async getStatistics(): Promise<DashboardStatistics> {
    return this.fetchJson("/api/statistics");
  }
}

export const api = new ApiClient();
export default api;
