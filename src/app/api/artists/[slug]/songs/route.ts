import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const sp = request.nextUrl.searchParams;
  return proxyBackend(`/api/artists/${encodeURIComponent(slug)}/songs`, {
    query: {
      year: sp.get("year") || undefined,
      limit: sp.get("limit") || undefined,
      offset: sp.get("offset") || undefined,
    },
  });
}
