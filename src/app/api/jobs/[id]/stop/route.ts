import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return proxyBackend(`/api/jobs/${id}/stop`, { method: "POST" });
}
