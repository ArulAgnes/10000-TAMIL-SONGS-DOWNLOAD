import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  return proxyBackend(`/api/artists/${encodeURIComponent(slug)}`);
}
