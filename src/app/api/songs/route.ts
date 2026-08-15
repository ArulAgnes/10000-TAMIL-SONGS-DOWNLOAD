import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  return proxyBackend("/api/songs", {
    query: {
      album_id: sp.get("album_id") || undefined,
      search: sp.get("search") || undefined,
      limit: sp.get("limit") || undefined,
      offset: sp.get("offset") || undefined,
    },
  });
}
