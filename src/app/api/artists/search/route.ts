import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams;
  return proxyBackend("/api/artists/search", {
    query: {
      q: sp.get("q") || undefined,
      limit: sp.get("limit") || undefined,
    },
  });
}
