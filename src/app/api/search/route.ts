import { NextRequest, NextResponse } from "next/server";
import { proxyBackend } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { query } = body;

  if (!query || query.trim().length < 2) {
    return NextResponse.json([]);
  }

  const response = await proxyBackend("/api/search", {
    method: "POST",
    body: { query, search_type: body.search_type || "all", year: body.year },
  });

  const payload = await response.json();
  if (!response.ok) return response;

  return NextResponse.json(payload.results ?? []);
}
