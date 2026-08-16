"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ArtistData, ArtistListResponse } from "@/lib/api";

const LETTERS = [
  "#", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
  "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
];

const PAGE_SIZE = 24;

export default function ArtistsPage() {
  const [letter, setLetter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("name");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<ArtistListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ArtistData[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchArtists = useCallback(
    async (opts?: { letter?: string; search?: string; sort?: string; offset?: number }) => {
      return api.getArtists({
        letter: opts?.letter ?? letter,
        search: (opts?.search ?? search) || undefined,
        sort: opts?.sort ?? sort,
        limit: PAGE_SIZE,
        offset: opts?.offset ?? offset,
      });
    },
    [letter, search, sort, offset],
  );

  useEffect(() => {
    let cancelled = false;
    fetchArtists()
      .then((result) => {
        if (cancelled) return;
        setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load artists");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchArtists]);

  const handleSearch = useCallback(
    (value: string) => {
      setSearch(value);
      setLetter("");
      setOffset(0);
      setLoading(true);
      setData(null);
      fetchArtists({ search: value, letter: "", offset: 0 })
        .then(setData)
        .catch((err) =>
          setError(err instanceof Error ? err.message : "Failed to load artists"),
        )
        .finally(() => setLoading(false));
    },
    [fetchArtists],
  );

  // Debounced autocomplete suggestions (DB-backed)
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      if (!search.trim()) {
        setSuggestions([]);
        return;
      }
      try {
        const res = await api.searchArtists(search.trim(), 8);
        setSuggestions(res.artists);
        setShowSuggestions(true);
      } catch {
        setSuggestions([]);
      }
    }, 250);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, [search]);

  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <main className="min-h-screen bg-gray-100">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Artists</h1>
          <p className="text-sm text-gray-500">
            A–Z directory of artists discovered across your collections.
          </p>
        </div>

        {/* Search */}
        <div className="relative mb-4">
          <input
            type="text"
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            onFocus={() => search.trim() && setShowSuggestions(true)}
            placeholder="Search artists… (e.g. Rahman)"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
          />
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-y-auto">
              {suggestions.map((artist) => (
                <Link
                  key={artist.id}
                  href={`/artists/${artist.slug}`}
                  onMouseDown={(e) => e.preventDefault()}
                  className="flex items-center justify-between px-4 py-2 hover:bg-gray-50"
                >
                  <span className="text-sm font-medium text-gray-900">{artist.name}</span>
                  <span className="text-xs text-gray-400">{artist.song_count} songs</span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* A-Z letter bar */}
        <div className="flex flex-wrap gap-1 mb-4">
          {LETTERS.map((l) => (
            <button
              key={l}
              onClick={() => {
                const next = letter === l ? "" : l;
                setLetter(next);
                setSearch("");
                setOffset(0);
                setLoading(true);
                fetchArtists({ letter: next, search: "", offset: 0 })
                  .then(setData)
                  .catch((err) =>
                    setError(err instanceof Error ? err.message : "Failed to load artists"),
                  )
                  .finally(() => setLoading(false));
              }}
              className={`w-8 h-8 flex items-center justify-center text-sm font-medium rounded transition-colors ${
                letter === l
                  ? "bg-blue-600 text-white"
                  : "bg-white border border-gray-200 text-gray-700 hover:bg-gray-50"
              }`}
              aria-label={`Filter by ${l}`}
            >
              {l}
            </button>
          ))}
        </div>

        {/* Sort */}
        <div className="flex items-center gap-2 mb-4">
          <span className="text-sm text-gray-600">Sort:</span>
          <select
            value={sort}
            onChange={(e) => {
              const next = e.target.value;
              setSort(next);
              setOffset(0);
              setLoading(true);
              fetchArtists({ sort: next, offset: 0 })
                .then(setData)
                .catch((err) =>
                  setError(err instanceof Error ? err.message : "Failed to load artists"),
                )
                .finally(() => setLoading(false));
            }}
            className="px-3 py-1.5 border border-gray-300 rounded-lg bg-white text-sm"
          >
            <option value="name">Name (A–Z)</option>
            <option value="song_count">Most songs</option>
          </select>
          <span className="ml-auto text-sm text-gray-500">
            {loading ? "Loading…" : `${total} artist${total === 1 ? "" : "s"}`}
          </span>
        </div>

        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        {loading && !data ? (
          <div className="text-center py-16">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto" />
          </div>
        ) : data && data.artists.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-lg border border-dashed border-gray-300">
            <p className="text-gray-500">
              No artists found. Analyze a collection or discover artists to populate this directory.
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {data?.artists.map((artist) => (
                <Link
                  key={artist.id}
                  href={`/artists/${artist.slug}`}
                  className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <p className="font-semibold text-gray-900 truncate">{artist.name}</p>
                      {artist.artist_type && artist.artist_type !== "UNKNOWN" && (
                        <p className="text-xs text-gray-500 mt-0.5">
                          {artist.artist_type.replace(/_/g, " ").toLowerCase()}
                        </p>
                      )}
                    </div>
                    <span className="shrink-0 px-2 py-1 bg-blue-50 text-blue-700 text-xs font-semibold rounded">
                      {artist.song_count} songs
                    </span>
                  </div>
                </Link>
              ))}
            </div>

            {pages > 1 && (
              <div className="flex items-center justify-center gap-3 mt-6">
                <button
                  onClick={() => {
                    const next = offset - PAGE_SIZE;
                    setOffset(Math.max(0, next));
                    setLoading(true);
                    fetchArtists({ offset: Math.max(0, next) })
                      .then(setData)
                      .catch((err) =>
                        setError(err instanceof Error ? err.message : "Failed to load artists"),
                      )
                      .finally(() => setLoading(false));
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
                    setLoading(true);
                    fetchArtists({ offset: next })
                      .then(setData)
                      .catch((err) =>
                        setError(err instanceof Error ? err.message : "Failed to load artists"),
                      )
                      .finally(() => setLoading(false));
                  }}
                  disabled={offset + PAGE_SIZE >= total}
                  className="px-4 py-2 border border-gray-300 rounded-lg bg-white text-sm font-medium hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next →
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
