// Server-side API client — proxies Next.js API routes to the FastAPI backend.
// Architecture: Next.js frontend → FastAPI backend (:8000) → database/filesystem.

import { NextResponse } from "next/server";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ProxyOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
}

/**
 * Forward a request to the FastAPI backend and return its JSON response
 * (status code preserved so the client-side api client can surface errors).
 */
export async function proxyBackend(
  path: string,
  opts: ProxyOptions = {},
): Promise<NextResponse> {
  const url = new URL(`${API_URL}${path}`);
  if (opts.query) {
    for (const [key, value] of Object.entries(opts.query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? "GET",
      headers:
        opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      {
        detail: `Backend API unreachable at ${API_URL}. Is the FastAPI server running? (${
          err instanceof Error ? err.message : String(err)
        })`,
      },
      { status: 502 },
    );
  }

  const text = await res.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = text;
  }

  return NextResponse.json(payload, { status: res.status });
}
