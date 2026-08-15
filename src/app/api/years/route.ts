import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyBackend("/api/years", {
    query: { job_id: request.nextUrl.searchParams.get("job_id") || undefined },
  });
}
