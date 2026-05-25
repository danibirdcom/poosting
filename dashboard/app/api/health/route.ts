import { NextResponse } from "next/server";
import { pingDb } from "@/lib/db";

/*
 * GET /api/health — health check para readiness probe.
 * Responde 200 si la app vive y la BD responde; 503 si la BD no.
 *
 * No requiere auth (es un endpoint de infra). PR2 lo mantiene público.
 */

export const dynamic = "force-dynamic";

export async function GET() {
  let db = false;
  try {
    db = await pingDb();
  } catch {
    db = false;
  }
  const body = { status: db ? "ok" : "degraded", db: db ? "ok" : "down" };
  return NextResponse.json(body, { status: db ? 200 : 503 });
}
