"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import type { CrawlProgress } from "@/lib/api";

interface ProgressTrackerProps {
  jobId: number;
  onComplete?: () => void;
}

const ProgressBar = ({ percentage, label }: { percentage: number; label: string }) => (
  <div className="mb-3">
    <div className="flex justify-between text-sm mb-1">
      <span className="text-gray-600">{label}</span>
      <span className="font-medium">{percentage.toFixed(1)}%</span>
    </div>
    <div className="w-full bg-gray-200 rounded-full h-2">
      <div
        className="bg-blue-600 h-2 rounded-full transition-all duration-500"
        style={{ width: `${Math.min(percentage, 100)}%` }}
      />
    </div>
  </div>
);

export default function ProgressTracker({ jobId, onComplete }: ProgressTrackerProps) {
  const [progress, setProgress] = useState<CrawlProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const completedRef = useRef(false);

  useEffect(() => {
    completedRef.current = false;

    // Connect to SSE endpoint for live progress
    const eventSource = new EventSource(`/api/jobs/${jobId}/progress`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const clamp = (value: number) => Math.max(0, Math.min(100, value));
        setProgress({
          job_id: data.jobId ?? jobId,
          status: data.status ?? "running",
          total_years: data.totalYears ?? 0,
          processed_years: data.processedYears ?? 0,
          year_progress: clamp(data.yearProgress ?? 0),
          total_pages: data.totalPages ?? 0,
          processed_pages: data.processedPages ?? 0,
          page_progress: clamp(data.pageProgress ?? 0),
          total_albums: data.totalAlbums ?? 0,
          processed_albums: data.processedAlbums ?? 0,
          album_progress: clamp(data.albumProgress ?? 0),
          total_songs: data.totalSongs ?? 0,
          processed_songs: data.processedSongs ?? 0,
          song_progress: clamp(data.songProgress ?? 0),
          overall_progress: clamp(data.overallProgress ?? 0),
          current_year: data.currentYear,
          current_page: data.currentPage,
          current_album: data.currentAlbum,
          current_song: data.currentSong,
          current_activity: data.currentActivity,
        });

        if (
          (data.status === "completed" || data.status === "failed" || data.status === "cancelled") &&
          !completedRef.current
        ) {
          completedRef.current = true;
          onComplete?.();
        }
      } catch {
        /* ignore parse errors */
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      // Fallback: poll once to get final status
      fetch(`/api/jobs/${jobId}`)
        .then(async (r) => {
          const data = await r.json().catch(() => ({}));
          if (!r.ok) {
            throw new Error(
              typeof data?.detail === "string"
                ? data.detail
                : `Job status request failed (HTTP ${r.status})`,
            );
          }
          if (!data || typeof data.status !== "string") {
            throw new Error("Unexpected job status response");
          }
          setProgress(data);
          if (
            (data.status === "completed" || data.status === "failed") &&
            !completedRef.current
          ) {
            completedRef.current = true;
            onComplete?.();
          }
        })
        .catch((e) => setError(e instanceof Error ? e.message : "Connection lost"));
    };

    return () => {
      eventSource.close();
    };
  }, [jobId, onComplete]);

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
        <p className="text-red-700">{error}</p>
      </div>
    );
  }

  if (!progress) {
    return (
      <div className="p-4 bg-gray-50 rounded-lg">
        <div className="flex items-center gap-2">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600" />
          <p className="text-gray-600">Connecting to crawler...</p>
        </div>
      </div>
    );
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed": return "text-green-600";
      case "failed": return "text-red-600";
      case "running": return "text-blue-600";
      case "cancelled": return "text-gray-600";
      default: return "text-gray-600";
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Analysis Progress</h3>
        <span className={`font-medium ${getStatusColor(progress.status)}`}>
          {progress.status.toUpperCase()}
        </span>
      </div>

      <div className="mb-6">
        <div className="text-3xl font-bold text-blue-600 mb-1">
          {progress.overall_progress.toFixed(1)}%
        </div>
        <p className="text-gray-500">Overall Progress</p>
      </div>

      <ProgressBar percentage={progress.year_progress} label="Years" />
      <ProgressBar percentage={progress.page_progress} label="Pages" />
      <ProgressBar percentage={progress.album_progress} label="Albums" />
      <ProgressBar percentage={progress.song_progress} label="Songs" />

      <div className="mt-6 grid grid-cols-2 gap-4 text-sm">
        <div className="bg-gray-50 p-3 rounded">
          <p className="text-gray-600">Years</p>
          <p className="font-semibold">{progress.processed_years} / {progress.total_years}</p>
        </div>
        <div className="bg-gray-50 p-3 rounded">
          <p className="text-gray-600">Pages</p>
          <p className="font-semibold">{progress.processed_pages} / {progress.total_pages}</p>
        </div>
        <div className="bg-gray-50 p-3 rounded">
          <p className="text-gray-600">Albums</p>
          <p className="font-semibold">{progress.total_albums} discovered</p>
        </div>
        <div className="bg-gray-50 p-3 rounded">
          <p className="text-gray-600">Songs</p>
          <p className="font-semibold">{progress.total_songs} discovered</p>
        </div>
      </div>

      {progress.current_activity && (
        <div className="mt-4 p-3 bg-blue-50 rounded-lg">
          <p className="text-sm text-blue-800 truncate">
            <span className="font-medium">Current:</span> {progress.current_activity}
          </p>
          {progress.current_year && (
            <p className="text-xs text-blue-600 mt-1">
              Year: {progress.current_year}
              {progress.current_page && ` · Page: ${progress.current_page}`}
            </p>
          )}
        </div>
      )}

      {progress.error && (
        <div className="mt-4 p-3 bg-red-50 rounded-lg">
          <p className="text-sm text-red-800">{progress.error}</p>
        </div>
      )}
    </div>
  );
}
