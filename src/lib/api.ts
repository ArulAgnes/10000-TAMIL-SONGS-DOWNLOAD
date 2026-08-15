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
  artist?: string;
  status: string;
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
