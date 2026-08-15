"use client";

import { useEffect, useState } from "react";
import { api, YearData } from "@/lib/api";

interface YearCardsProps {
  onSelectYear: (year: YearData) => void;
  refreshKey?: number;
}

export default function YearCards({ onSelectYear, refreshKey }: YearCardsProps) {
  const [years, setYears] = useState<YearData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchYears = async () => {
      try {
        const data = await api.getYears();
        if (!cancelled) {
          setYears(data.sort((a, b) => a.year - b.year));
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchYears();
    const interval = setInterval(fetchYears, 5000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [refreshKey]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (years.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow-lg p-8 text-center text-gray-500">
        <p className="text-lg">No years discovered yet.</p>
        <p className="text-sm mt-2">Enter a URL and start an analysis to begin.</p>
      </div>
    );
  }

  const statusStyle: Record<string, string> = {
    completed: "bg-green-100 border-green-300",
    running: "bg-blue-100 border-blue-300 animate-pulse",
    failed: "bg-red-100 border-red-300",
    pending: "bg-gray-100 border-gray-300",
  };

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <h3 className="text-lg font-semibold mb-4">
        Discovered Years ({years.length})
      </h3>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-3">
        {years.map((yr) => (
          <button
            key={yr.id}
            onClick={() => onSelectYear(yr)}
            className={`p-3 rounded-lg border-2 transition-all hover:shadow-md cursor-pointer ${statusStyle[yr.status] ?? "bg-gray-100 border-gray-300"}`}
          >
            <div className="text-lg font-bold">{yr.year}</div>
            <div className="text-xs text-gray-600 mt-1">{yr.total_albums} albums</div>
            <div className="text-xs text-gray-500">{yr.total_songs} songs</div>
          </button>
        ))}
      </div>
    </div>
  );
}
