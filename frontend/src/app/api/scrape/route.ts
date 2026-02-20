/**
 * Custom proxy for POST /api/scrape
 *
 * Next.js rewrite proxies have a ~30s socket timeout which Playwright-based scraping
 * can exceed. This Route Handler has no proxy timeout and handles the full duration.
 * It takes precedence over the catch-all rewrite in next.config.js.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  const body = await request.json();

  try {
    const res = await fetch(`${BACKEND}/scrape`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      // 2-minute timeout — enough for Playwright launch + Cloudflare challenge + Groq
      signal: AbortSignal.timeout(120_000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "TimeoutError") {
      return NextResponse.json(
        { detail: "Scrape timed out after 2 minutes. The page took too long to load." },
        { status: 408 }
      );
    }
    return NextResponse.json({ detail: String(err) }, { status: 502 });
  }
}
