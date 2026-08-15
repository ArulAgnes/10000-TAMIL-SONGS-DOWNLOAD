"use client";

import { useEffect, useState } from "react";
import { api, DashboardStatistics } from "@/lib/api";

const formatNumber = (num: number) => {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num.toString();
};

const StatCard = ({
  label,
  value,
  color = "blue",
}: {
  label: string;
  value: number;
  color?: "blue" | "green" | "purple" | "orange";
}) => {
  const colors = {
    blue: "bg-blue-50 border-blue-200",
    green: "bg-green-50 border-green-200",
    purple: "bg-purple-50 border-purple-200",
    orange: "bg-orange-50 border-orange-200",
  };

  return (
    <div className={`p-4 rounded-lg border-2 ${colors[color]}`}>
      <p className="text-sm text-gray-600 mb-1">{label}</p>
      <p className="text-2xl font-bold">{formatNumber(value)}</p>
    </div>
  );
};

export default function Statistics() {
  const [stats, setStats] = useState<DashboardStatistics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const data = await api.getStatistics();
        setStats(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch statistics");
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
    const interval = setInterval(fetchStats, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {["years", "albums", "songs", "resources"].map((label) => (
          <div key={`skeleton-${label}`} className="bg-gray-100 animate-pulse h-24 rounded-lg"></div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
        <p className="text-red-700">{error}</p>
      </div>
    );
  }

  if (!stats) return null;

  const { overview } = stats;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Years" value={overview.total_years} color="blue" />
        <StatCard label="Albums" value={overview.total_albums} color="green" />
        <StatCard label="Songs" value={overview.total_songs} color="purple" />
        <StatCard label="Resources" value={overview.total_audio_resources} color="orange" />
      </div>

      {stats.recent_jobs.length > 0 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h4 className="font-semibold mb-3">Recent Analysis Jobs</h4>
          <div className="space-y-2">
            {stats.recent_jobs.map((job) => (
              <div key={job.id} className="flex justify-between items-center p-2 bg-gray-50 rounded">
                <div className="truncate flex-1 mr-4">
                  <span className="text-sm font-medium">{job.base_url}</span>
                </div>
                <span className={`text-xs px-2 py-1 rounded ${
                  job.status === "completed" ? "bg-green-100 text-green-800" :
                  job.status === "running" ? "bg-blue-100 text-blue-800" :
                  job.status === "failed" ? "bg-red-100 text-red-800" :
                  "bg-gray-100 text-gray-800"
                }`}>
                  {job.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
