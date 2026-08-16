"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, CollectionProgress, CollectionStatus, ArchiveData } from "@/lib/api";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const POLL_MS = 2000;

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

function formatElapsed(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "--:--";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

export default function CollectionPanel() {
  const [baseUrl, setBaseUrl] = useState("");
  const [startYear, setStartYear] = useState("1990");
  const [endYear, setEndYear] = useState("2026");
  const [prefix, setPrefix] = useState("Tamil_Songs_");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [jobId, setJobId] = useState<number | null>(null);
  const [status, setStatus] = useState<CollectionStatus | null>(null);
  const [progress, setProgress] = useState<CollectionProgress | null>(null);
  const [archive, setArchive] = useState<ArchiveData | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const startedAtRef = useRef<number | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  // Live tick for elapsed time while running
  useEffect(() => {
    if (jobId === null || (status && TERMINAL.has(status.status))) return;
    const tick = setInterval(() => {
      if (startedAtRef.current) setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
    }, 1000);
    return () => clearInterval(tick);
  }, [jobId, status]);

  const poll = useCallback(async () => {
    if (jobId === null) return;
    try {
      const [prog, coll] = await Promise.all([
        api.getCollectionProgress(jobId),
        api.getCollection(jobId),
      ]);
      setProgress(prog);
      setStatus(coll);
      if (prog.started_at && startedAtRef.current === null) {
        startedAtRef.current = Date.now();
      }
      setElapsed(prog.elapsed_seconds ?? elapsed);
      if (TERMINAL.has(coll.status)) {
        stopPolling();
        // Auto-check for an archive once the crawl finishes
        try {
          const existing = await api.getCollectionArchive(jobId);
          setArchive(existing);
        } catch {
          /* no archive yet */
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to poll collection progress");
    }
  }, [jobId, elapsed, stopPolling]);

  useEffect(() => {
    if (jobId === null) return;
    stopPolling();
    const initial = setTimeout(() => poll(), 0);
    pollTimer.current = setInterval(poll, POLL_MS);
    return () => {
      clearTimeout(initial);
      stopPolling();
    };
  }, [jobId, poll, stopPolling]);

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setArchive(null);
    setArchiveError(null);
    const start = parseInt(startYear, 10);
    const end = parseInt(endYear, 10);
    if (Number.isNaN(start) || Number.isNaN(end)) {
      setError("Please enter valid start and end years.");
      return;
    }
    if (start > end) {
      setError("Start year must be less than or equal to end year.");
      return;
    }

    setStarting(true);
    try {
      const res = await api.createCollection({
        base_url: baseUrl,
        start_year: start,
        end_year: end,
        archive_prefix: prefix,
      });
      setJobId(res.job_id);
      startedAtRef.current = null;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start collection");
    } finally {
      setStarting(false);
    }
  };

  const handleCancel = async () => {
    if (jobId === null) return;
    try {
      await api.cancelCollection(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel collection");
    }
  };

  const handleCreateArchive = async () => {
    if (jobId === null) return;
    setArchiving(true);
    setArchiveError(null);
    try {
      const arch = await api.createCollectionArchive(jobId, { prefix });
      setArchive(arch);
    } catch (err) {
      setArchiveError(err instanceof Error ? err.message : "Failed to create archive");
    } finally {
      setArchiving(false);
    }
  };

  const handleCancelArchive = async () => {
    if (jobId === null) return;
    try {
      await api.cancelCollectionArchive(jobId);
    } catch (err) {
      setArchiveError(err instanceof Error ? err.message : "Failed to cancel archive");
    }
  };

  const finished = status !== null && TERMINAL.has(status.status);
  const pct = progress?.progress_percentage ?? 0;

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Multi-Year Collection</h2>
      <p className="text-xs text-gray-500 mb-4">
        Crawl a year range in one job and produce a single combined ZIP archive.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      )}

      {jobId === null ? (
        <form onSubmit={handleStart} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Category URL
            </label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://example.com/category/latest-tamil-songs/{year}"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              required
            />
            <p className="mt-1 text-xs text-gray-500">
              Supports a {"{year}"} placeholder replaced for each year in the range.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Start Year</label>
              <input
                type="number"
                value={startYear}
                onChange={(e) => setStartYear(e.target.value)}
                min={1900}
                max={2100}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">End Year</label>
              <input
                type="number"
                value={endYear}
                onChange={(e) => setEndYear(e.target.value)}
                min={1900}
                max={2100}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Archive prefix
            </label>
            <input
              type="text"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              placeholder="Tamil_Songs_"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            />
            <p className="mt-1 text-xs text-gray-500">
              Archive will be named like <code>{prefix || "Tamil_Songs_"}1990-1992.zip</code>.
            </p>
          </div>

          <button
            type="submit"
            disabled={starting}
            className="w-full py-3 px-6 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white font-semibold rounded-lg transition-colors"
          >
            {starting ? "Starting Collection…" : "Start Collection"}
          </button>
        </form>
      ) : (
        <div className="space-y-4">
          {/* Progress */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-gray-700">
                Collection #{jobId} · <span className="capitalize">{status?.status}</span>
              </span>
              <span className="text-sm text-gray-600 tabular-nums">
                {Math.round(pct)}%
              </span>
            </div>
            <div className="h-2.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-600 transition-all"
                style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
              />
            </div>
            <div className="mt-2 text-xs text-gray-500 space-y-0.5">
              <p>
                Years {progress?.completed_years ?? 0}/{progress?.total_years ?? 0} · Albums{" "}
                {progress?.total_albums ?? 0} · Songs {progress?.total_songs ?? 0}
              </p>
              {progress?.current_year && (
                <p>
                  Now: {progress.current_year}
                  {progress.current_album ? ` · ${progress.current_album}` : ""}
                  {progress.current_song ? ` · ${progress.current_song}` : ""}
                </p>
              )}
              <p>
                {progress?.failed_urls ? `Failed URLs: ${progress.failed_urls} · ` : ""}
                {progress?.skipped_urls ? `Skipped: ${progress.skipped_urls} · ` : ""}
                Elapsed: {formatElapsed(elapsed ?? progress?.elapsed_seconds)}
              </p>
              {progress?.error_message && (
                <p className="text-red-600">{progress.error_message}</p>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            {!finished && (
              <button
                onClick={handleCancel}
                className="flex-1 py-2 px-4 border border-red-300 text-red-700 rounded-lg font-medium hover:bg-red-50 transition-colors"
              >
                Cancel
              </button>
            )}
            {finished && status?.status === "completed" && (
              <button
                onClick={handleCreateArchive}
                disabled={archiving}
                className="flex-1 py-2 px-4 bg-green-600 hover:bg-green-700 disabled:bg-gray-400 text-white font-medium rounded-lg transition-colors"
              >
                {archiving ? "Creating Archive…" : "Create Combined ZIP"}
              </button>
            )}
          </div>

          {/* Archive */}
          {archiveError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-red-700 text-sm">{archiveError}</p>
            </div>
          )}

          {archive && (
            <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg">
              {archive.status === "running" || archive.status === "pending" ? (
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-2">
                    Building <span className="font-mono">{archive.name}</span>…
                  </p>
                  <button
                    onClick={handleCancelArchive}
                    className="py-1.5 px-3 border border-red-300 text-red-700 text-sm rounded-lg hover:bg-red-50"
                  >
                    Cancel archive
                  </button>
                </div>
              ) : archive.status === "completed" ? (
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">
                      <span className="font-mono">{archive.name}</span>
                    </p>
                    <p className="text-xs text-gray-500">
                      {archive.file_count} files · {formatBytes(archive.size_bytes)}
                    </p>
                  </div>
                  {archive.download_url && (
                    <a
                      href={archive.download_url}
                      className="shrink-0 ml-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg"
                    >
                      Download ZIP
                    </a>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-600">
                  Archive status: <span className="capitalize">{archive.status}</span>
                  {archive.error_message ? ` — ${archive.error_message}` : ""}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
