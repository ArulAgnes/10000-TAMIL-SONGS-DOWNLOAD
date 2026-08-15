"use client";

import { useState, useCallback } from "react";
import AnalyzerForm from "@/components/dashboard/AnalyzerForm";
import ProgressTracker from "@/components/dashboard/ProgressTracker";
import YearCards from "@/components/dashboard/YearCards";
import YearDetail from "@/components/dashboard/YearDetail";
import Statistics from "@/components/dashboard/Statistics";
import { api, YearData } from "@/lib/api";

export default function Dashboard() {
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [selectedYear, setSelectedYear] = useState<YearData | null>(null);
  const [showStats, setShowStats] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleAnalysisStarted = useCallback((jobId: number) => {
    setActiveJobId(jobId);
  }, []);

  const handleAnalysisComplete = useCallback(() => {
    setRefreshKey((prev) => prev + 1);
  }, []);

  const handleDownloadYear = useCallback(async (yearId: number) => {
    try {
      await api.downloadYear(yearId);
      alert("Download started! Check the Archives section for progress.");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to start download");
    }
  }, []);

  return (
    <main className="min-h-screen bg-gray-100">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">
                🎵 Audio Collection Analyzer
              </h1>
              <p className="text-sm text-gray-500">
                Crawl audio sites by year, discover albums &amp; songs, download authorized ZIPs
              </p>
            </div>
            <nav className="flex gap-4">
              <button
                onClick={() => setShowStats(!showStats)}
                className="text-sm text-gray-600 hover:text-gray-900 px-3 py-1 rounded border"
              >
                {showStats ? "Hide Stats" : "Show Stats"}
              </button>
            </nav>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column */}
          <div className="lg:col-span-1 space-y-6">
            <AnalyzerForm onAnalysisStarted={handleAnalysisStarted} />

            {activeJobId && (
              <ProgressTracker
                key={activeJobId}
                jobId={activeJobId}
                onComplete={handleAnalysisComplete}
              />
            )}
          </div>

          {/* Right Column */}
          <div className="lg:col-span-2 space-y-6">
            {showStats && <Statistics key={`stats-${refreshKey}`} />}

            <YearCards
              key={`years-${refreshKey}`}
              refreshKey={refreshKey}
              onSelectYear={setSelectedYear}
            />
          </div>
        </div>
      </div>

      {/* Year Detail Modal */}
      {selectedYear && (
        <YearDetail
          year={selectedYear}
          onClose={() => setSelectedYear(null)}
          onDownload={handleDownloadYear}
        />
      )}

      <footer className="bg-white border-t mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <p className="text-center text-gray-500 text-sm">
            Audio Collection Analyzer — Only downloads authorized resources
          </p>
        </div>
      </footer>
    </main>
  );
}
