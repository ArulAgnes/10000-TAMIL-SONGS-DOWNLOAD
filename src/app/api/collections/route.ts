import { NextRequest } from "next/server";
import { proxyBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.json();
  return proxyBackend("/api/collections", { method: "POST", body });
}
