import { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { proxyBackend } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { base_url, start_year, end_year } = body;

  if (!base_url || start_year == null || end_year == null) {
    return NextResponse.json(
      { detail: "Missing required fields: base_url, start_year, end_year" },
      { status: 400 },
    );
  }

  if (start_year > end_year) {
    return NextResponse.json(
      { detail: "start_year must be <= end_year" },
      { status: 400 },
    );
  }

  return proxyBackend("/api/analyze", { method: "POST", body });
}
