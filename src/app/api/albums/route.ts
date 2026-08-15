import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  return proxyBackend("/api/albums", {
    query: {
      year_id: sp.get("year_id") || undefined,
      search: sp.get("search") || undefined,
      limit: sp.get("limit") || undefined,
      offset: sp.get("offset") || undefined,
    },
  });
}
