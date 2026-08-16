import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  return proxyBackend("/api/artists", {
    query: {
      letter: sp.get("letter") || undefined,
      search: sp.get("search") || undefined,
      sort: sp.get("sort") || undefined,
      limit: sp.get("limit") || undefined,
      offset: sp.get("offset") || undefined,
    },
  });
}
