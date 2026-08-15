"use client";

import { useState, useEffect } from "react";
import { api, YearData, AlbumData } from "@/lib/api";

interface YearDetailProps {
  year: YearData;
  onClose: () => void;
  onDownload: (yearId: number) => void;
}

export default function YearDetail({ year, onClose, onDownload }: YearDetailProps) {
  const [albums, setAlbums] = useState<AlbumData[]>([]);
  const [expandedAlbum, setExpandedAlbum] = useState<number | null>(null);
  const [albumDetails, setAlbumDetails] = useState<Record<number, AlbumData>>({});
  const [loadingAlbums, setLoadingAlbums] = useState(true);
  const [albumsError, setAlbumsError] = useState<string | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.getAlbums({ year_id: year.id, limit: 100 }).then(
      (data) => {
        if (cancelled) return;
        setAlbums(data);
        setLoadingAlbums(false);
      },
      (err) => {
        if (cancelled) return;
        setAlbumsError(err instanceof Error ? err.message : "Failed to load albums");
        setLoadingAlbums(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [year.id]);

  const toggleAlbum = async (albumId: number) => {
    if (expandedAlbum === albumId) {
      setExpandedAlbum(null);
      return;
    }
    setExpandedAlbum(albumId);
    if (!albumDetails[albumId]) {
      try {
        const detail = await api.getAlbum(albumId);
        setAlbumDetails((prev) => ({ ...prev, [albumId]: detail }));
      } catch (err) {
        setAlbumsError(err instanceof Error ? err.message : "Failed to load album details");
      }
    }
  };

  const statusBadge: Record<string, string> = {
    completed: "bg-green-100 text-green-800",
    running: "bg-blue-100 text-blue-800",
    pending: "bg-yellow-100 text-yellow-800",
    failed: "bg-red-100 text-red-800",
    authorized: "bg-green-100 text-green-800",
    none: "bg-gray-100 text-gray-600",
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50 overflow-y-auto">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full p-6 my-8 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex justify-between items-start mb-4">
          <div>
            <h2 className="text-2xl font-bold">{year.year}</h2>
            <span className={`inline-block mt-1 px-2 py-1 text-xs rounded ${statusBadge[year.status] || "bg-gray-100"}`}>
              {year.status}
            </span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="text-center p-3 bg-blue-50 rounded">
            <div className="text-xl font-bold text-blue-600">{year.total_pages}</div>
            <div className="text-xs text-gray-600">Pages</div>
          </div>
          <div className="text-center p-3 bg-green-50 rounded">
            <div className="text-xl font-bold text-green-600">{year.total_albums}</div>
            <div className="text-xs text-gray-600">Albums</div>
          </div>
          <div className="text-center p-3 bg-purple-50 rounded">
            <div className="text-xl font-bold text-purple-600">{year.total_songs}</div>
            <div className="text-xs text-gray-600">Songs</div>
          </div>
        </div>

        {/* Albums */}
        <div className="mb-6">
          <h3 className="font-semibold text-gray-800 mb-3">Albums ({albums.length})</h3>
          {albumsError && (
            <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-red-700 text-sm">{albumsError}</p>
            </div>
          )}
          {loadingAlbums ? (
            <div className="text-center py-4">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto" />
            </div>
          ) : (
            <div className="space-y-1 max-h-60 overflow-y-auto border rounded-lg">
              {albums.map((album) => (
                <div key={album.id} className="border-b border-gray-100 last:border-0">
                  <button
                    onClick={() => toggleAlbum(album.id)}
                    className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-50 text-left transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <span className="font-medium text-sm text-gray-900 truncate block">{album.title}</span>
                      <span className="text-xs text-gray-500">
                        {album.artist || album.music_director || ""}
                        {album.zip_url && <span className="ml-1 text-green-600">· ZIP available</span>}
                      </span>
                    </div>
                    <span className="text-gray-400 text-xs ml-2">{expandedAlbum === album.id ? "▲" : "▼"}</span>
                  </button>

                  {expandedAlbum === album.id && albumDetails[album.id] && (
                    <div className="px-3 pb-3 bg-gray-50">
                      <div className="text-xs text-gray-600 space-y-1 pt-1">
                        {albumDetails[album.id].description && (
                          <p className="italic mb-2">{albumDetails[album.id].description}</p>
                        )}
                        {albumDetails[album.id].zip_url && (
                          <p>
                            <span className="font-medium text-green-700">ZIP Download:</span>{" "}
                            <a href={albumDetails[album.id].zip_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">
                              Download All Songs (ZIP)
                            </a>
                          </p>
                        )}
                      </div>
                      {albumDetails[album.id].songs && albumDetails[album.id].songs!.length > 0 && (
                        <div className="mt-2 space-y-1">
                          {albumDetails[album.id].songs!.map((s) => (
                            <div key={s.id} className="flex items-center justify-between text-xs py-1 px-2 bg-white rounded">
                              <span>
                                <span className="text-gray-400 mr-1">{s.track_number}.</span>
                                {s.title}
                              </span>
                              <div className="flex items-center gap-2">
                                {s.duration && <span className="text-gray-400">{s.duration}</span>}
                                <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${statusBadge[s.status] || "bg-gray-100"}`}>
                                  {s.status}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={() => { setIsDownloading(true); onDownload(year.id); }}
            disabled={isDownloading || year.total_songs === 0}
            className="flex-1 py-2 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white rounded-lg font-medium transition-colors"
          >
            {isDownloading ? "Starting..." : `Download ${year.year} Collection`}
          </button>
          <button onClick={onClose} className="py-2 px-4 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
