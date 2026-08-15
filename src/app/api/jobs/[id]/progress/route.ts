import { NextRequest } from "next/server";
import { API_URL } from "@/lib/backend";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const POLL_INTERVAL_MS = 2000;

interface BackendJob {
  job_id: number;
  status: string;
  total_years: number;
  processed_years: number;
  total_pages: number;
  processed_pages: number;
  total_albums: number;
  processed_albums: number;
  total_songs: number;
  processed_songs: number;
  overall_progress: number;
  current_year?: number;
  current_page?: number;
  current_album?: string;
  current_song?: string;
  current_activity?: string;
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

/** Percentages must never exceed 100, even with stale counters. */
const clamp = (value: number) => Math.max(0, Math.min(100, value));

const pct = (processed: number, total: number) =>
  total > 0 ? clamp((processed / total) * 100) : 0;

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const jobId = parseInt(id, 10);

  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      let closed = false;
      const send = (data: unknown) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
        } catch {
          closed = true;
        }
      };

      const poll = async () => {
        try {
          const res = await fetch(`${API_URL}/api/jobs/${jobId}`, {
            cache: "no-store",
            headers: { Accept: "application/json" },
          });
          if (!res.ok) {
            if (res.status === 404) {
              send({ jobId, status: "failed", error: "Job not found" });
              cleanup();
              return;
            }
            return;
          }
          const job: BackendJob = await res.json();
          const overall =
            job.overall_progress !== undefined && job.overall_progress !== null
              ? clamp(job.overall_progress)
              : pct(job.processed_years, job.total_years);

          send({
            jobId: job.job_id ?? jobId,
            status: job.status,
            totalYears: job.total_years,
            processedYears: job.processed_years,
            totalPages: job.total_pages,
            processedPages: job.processed_pages,
            totalAlbums: job.total_albums,
            processedAlbums: job.processed_albums,
            totalSongs: job.total_songs,
            processedSongs: job.processed_songs,
            overallProgress: overall,
            yearProgress: pct(job.processed_years, job.total_years),
            pageProgress: pct(job.processed_pages, job.total_pages),
            albumProgress: pct(job.processed_albums, job.total_albums),
            songProgress: pct(job.processed_songs, job.total_songs),
            currentYear: job.current_year,
            currentPage: job.current_page,
            currentAlbum: job.current_album,
            currentSong: job.current_song,
            currentActivity: job.current_activity,
          });

          if (TERMINAL_STATUSES.has(job.status)) {
            cleanup();
          }
        } catch {
          send({
            jobId,
            status: "error",
            currentActivity: `Backend API unreachable at ${API_URL}`,
          });
        }
      };

      let pollTimer: ReturnType<typeof setInterval> | null = null;
      let closedFired = false;

      const cleanup = () => {
        if (closedFired) return;
        closedFired = true;
        closed = true;
        if (pollTimer) clearInterval(pollTimer);
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      };

      pollTimer = setInterval(poll, POLL_INTERVAL_MS);
      await poll();

      _req.signal.addEventListener("abort", cleanup);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
