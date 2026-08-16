"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ArtistData, ArtistSongData, formatDuration } from "@/lib/api";

const PAGE_SIZE = 50;

const statusBadge: Record<string, string> = {
  completed: "bg-green-100 text-green-800",
  running: "bg-blue-100 text-blue-800",
  pending: "bg-yellow-100 text-yellow-800",
  failed: "bg-red-100 text-red-800",
};

export default function ArtistDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const [artist, setArtist] = useState<ArtistData | null>(null);
  const [songs, setSongs] = useState<ArtistSongData[]>([]);
  const [years, setYears] = useState<number[]>([]);
  const [selectedYear, setSelectedYear] = useState<number | "">("");
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingSongs, setLoadingSongs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeMsg, setAnalyzeMsg] = useState<string | null>(null);

  const fetchArtist = useCallback(async (): Promise<[ArtistData, number[]]> => {
    const [artistData, yearsData] = await Promise.all([
      api.getArtist(slug),
      api.getArtistYears(slug),
    ]);
    return [artistData, yearsData];
  }, [slug]);

  const fetchSongs = useCallback(
    async (year: number | "", off: number) => {
      return api.getArtistSongs(slug, {
        year: year === "" ? undefined : year,
        limit: PAGE_SIZE,
        offset: off,
      });
    },
    [slug],
  );

  useEffect(() => {
    let cancelled = false;
    fetchArtist()
      .then(([artistData, yearsData]) => {
        if (cancelled) return;
        setArtist(artistData);
        setYears(yearsData);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load artist");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchArtist]);

  useEffect(() => {
    let cancelled = false;
    fetchSongs(selectedYear, offset)
      .then((res) => {
        if (cancelled) return;
        setSongs(res.songs);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load songs");
      })
      .finally(() => {
        if (!cancelled) setLoadingSongs(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchSongs, selectedYear, offset]);

  const handleAnalyze = async () => {
    if (!artist) return;
    setAnalyzing(true);
    setAnalyzeMsg(null);
    try {
      const res = await api.analyzeArtist({ artist_id: artist.id });
      setAnalyzeMsg(res.message || (res.status === "cancelled" ? "Analysis cancelled" : "Analysis started"));
    } catch (err) {
      setAnalyzeMsg(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen bg-gray-100">
        <div className="max-w-4xl mx-auto px-4 py-16 text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto" />
        </div>
      </main>
    );
  }

  if (error && !artist) {
    return (
      <main className="min-h-screen bg-gray-100">
        <div className="max-w-4xl mx-auto px-4 py-16">
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-700">{error}</p>
          </div>
          <Link href="/artists" className="text-blue-600 text-sm mt-4 inline-block">
            ← Back to artists
          </Link>
        </div>
      </main>
    );
  }

  if (!artist) return null;

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <main className="min-h-screen bg-gray-100">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Link href="/artists" className="text-sm text-blue-600 hover:text-blue-800">
          ← Back to artists
        </Link>

        {/* Artist header */}
        <div className="mt-4 bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">{artist.name}</h1>
              {artist.artist_type && artist.artist_type !== "UNKNOWN" && (
                <p className="text-sm text-gray-500 mt-1">
                  {artist.artist_type.replace(/_/g, " ").toLowerCase()}
                </p>
              )}
              {artist.source_url && (
                <a
                  href={artist.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 underline mt-1 inline-block break-all"
                >
                  Source page
                </a>
              )}
            </div>
            <div className="flex flex-col items-end gap-2">
              <span className="px-3 py-1 bg-blue-50 text-blue-700 text-sm font-semibold rounded">
                {total} songs
              </span>
              <button
                onClick={handleAnalyze}
                disabled={analyzing}
                className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {analyzing ? "Starting…" : "Analyze artist"}
              </button>
            </div>
          </div>
          {analyzeMsg && <p className="mt-3 text-sm text-gray-600">{analyzeMsg}</p>}
        </div>

        {/* Year filter */}
        {years.length > 0 && (
          <div className="mt-4 flex items-center gap-2">
            <span className="text-sm text-gray-600">Year:</span>
            <select
              value={selectedYear}
              onChange={(e) => {
                const next = e.target.value === "" ? "" : parseInt(e.target.value, 10);
                setSelectedYear(next);
                setOffset(0);
                setLoadingSongs(true);
              }}
              className="px-3 py-1.5 border border-gray-300 rounded-lg bg-white text-sm"
            >
              <option value="">All years</option>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Songs */}
        <div className="mt-4 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-800">Songs</h2>
            <span className="text-xs text-gray-500">{total} total</span>
          </div>

          {loadingSongs ? (
            <div className="text-center py-10">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto" />
            </div>
          ) : songs.length === 0 ? (
            <div className="text-center py-10">
              <p className="text-gray-500">No songs found for this artist.</p>
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {songs.map((song) => (
                <li key={song.id} className="px-4 py-3 flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{song.title}</p>
                    <p className="text-xs text-gray-500 truncate">
                      {song.year}
                      {song.album ? ` · ${song.album}` : ""}
                      {song.track_number ? ` · Track ${song.track_number}` : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-sm text-gray-500 tabular-nums">
                      {song.duration_seconds != null
                        ? formatDuration(song.duration_seconds)
                        : song.duration || "--:--"}
                    </span>
                    {song.status && (
                      <span
                        className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                          statusBadge[song.status] || "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {song.status}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {pages > 1 && (
          <div className="flex items-center justify-center gap-3 mt-6">
            <button
              onClick={() => {
                const next = Math.max(0, offset - PAGE_SIZE);
                setOffset(next);
                setLoadingSongs(true);
              }}
              disabled={offset === 0}
              className="px-4 py-2 border border-gray-300 rounded-lg bg-white text-sm font-medium hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              ← Prev
            </button>
            <span className="text-sm text-gray-600">
              Page {page} of {pages}
            </span>
            <button
              onClick={() => {
                const next = offset + PAGE_SIZE;
                setOffset(next);
                setLoadingSongs(true);
              }}
              disabled={offset + PAGE_SIZE >= total}
              className="px-4 py-2 border border-gray-300 rounded-lg bg-white text-sm font-medium hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
