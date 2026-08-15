"use client";

import { useState } from "react";
import { api, CrawlerConfig } from "@/lib/api";

interface AnalyzerFormProps {
  onAnalysisStarted: (jobId: number) => void;
}

export default function AnalyzerForm({ onAnalysisStarted }: AnalyzerFormProps) {
  const [baseUrl, setBaseUrl] = useState("");
  const [startYear, setStartYear] = useState("1990");
  const [endYear, setEndYear] = useState("2026");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Advanced options
  const [maxConcurrency, setMaxConcurrency] = useState("5");
  const [requestTimeout, setRequestTimeout] = useState("30");
  const [maxRetries, setMaxRetries] = useState("3");
  const [requestDelay, setRequestDelay] = useState("500");

  const parseNum = (value: string): number | undefined => {
    const n = parseInt(value, 10);
    return Number.isNaN(n) ? undefined : n;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const start = parseNum(startYear);
    const end = parseNum(endYear);
    if (start === undefined || end === undefined) {
      setError("Please enter valid start and end years.");
      return;
    }
    if (start > end) {
      setError("Start year must be less than or equal to end year.");
      return;
    }

    setIsLoading(true);

    try {
      const config: CrawlerConfig | undefined = showAdvanced ? {
        max_concurrency: parseNum(maxConcurrency),
        request_timeout: parseNum(requestTimeout),
        max_retries: parseNum(maxRetries),
        request_delay_ms: parseNum(requestDelay),
      } : undefined;

      const response = await api.startAnalysis({
        base_url: baseUrl,
        start_year: start,
        end_year: end,
        config,
      });

      onAnalysisStarted(response.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <h2 className="text-2xl font-bold text-gray-900 mb-6">
        Audio Collection Analyzer
      </h2>

      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-700">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Website / Category URL
          </label>
          <input
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://example.com/category/latest-tamil-songs/2026"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            required
          />
          <p className="mt-1 text-xs text-gray-500">
            The final year (for example, 2026) is replaced automatically for the selected range. A {"{year}"} placeholder is also supported.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Start Year
            </label>
            <input
              type="number"
              value={startYear}
              onChange={(e) => setStartYear(e.target.value)}
              min={1900}
              max={2100}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              End Year
            </label>
            <input
              type="number"
              value={endYear}
              onChange={(e) => setEndYear(e.target.value)}
              min={1900}
              max={2100}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              required
            />
          </div>
        </div>

        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          {showAdvanced ? "Hide Advanced Options" : "Show Advanced Options"}
        </button>

        {showAdvanced && (
          <div className="grid grid-cols-2 gap-4 p-4 bg-gray-50 rounded-lg">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Max Concurrency
              </label>
              <input
                type="number"
                value={maxConcurrency}
                onChange={(e) => setMaxConcurrency(e.target.value)}
                min={1}
                max={20}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Request Timeout (s)
              </label>
              <input
                type="number"
                value={requestTimeout}
                onChange={(e) => setRequestTimeout(e.target.value)}
                min={5}
                max={120}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Max Retries
              </label>
              <input
                type="number"
                value={maxRetries}
                onChange={(e) => setMaxRetries(e.target.value)}
                min={0}
                max={10}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Request Delay (ms)
              </label>
              <input
                type="number"
                value={requestDelay}
                onChange={(e) => setRequestDelay(e.target.value)}
                min={0}
                max={5000}
                step={100}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg"
              />
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={isLoading}
          className="w-full py-3 px-6 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white font-semibold rounded-lg transition-colors"
        >
          {isLoading ? "Starting Analysis..." : "Analyze Collection"}
        </button>
      </form>
    </div>
  );
}
