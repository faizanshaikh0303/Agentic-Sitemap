"use client";

import { useState } from "react";

const STOCK_STYLES: Record<string, string> = {
  in_stock: "bg-green-900/60 text-green-300 border-green-800",
  out_of_stock: "bg-red-900/60 text-red-300 border-red-800",
  unknown: "bg-gray-800 text-gray-400 border-gray-700",
};

const SENTIMENT_COLORS: Record<string, string> = {
  positive: "text-green-400",
  neutral: "text-yellow-400",
  negative: "text-red-400",
};

function safeHostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

interface ProductCardProps {
  product: {
    id: number;
    url: string;
    title: string;
    price?: string;
    summary?: Record<string, unknown>;
  };
  onDelete: () => void;
  onRescrape: () => void;
}

type CardState = "idle" | "scraping" | "deleting";

export default function ProductCard({ product, onDelete, onRescrape }: ProductCardProps) {
  const [state, setState] = useState<CardState>("idle");
  const s = (product.summary ?? {}) as Record<string, string | number>;

  const stockStyle =
    STOCK_STYLES[(s.stock_status as string) ?? "unknown"] ?? STOCK_STYLES.unknown;
  const sentimentColor =
    SENTIMENT_COLORS[(s.sentiment as string) ?? "neutral"] ?? SENTIMENT_COLORS.neutral;
  const confidence = typeof s.confidence === "number" ? s.confidence : 0.5;
  const isStale = confidence < 0.15 || !(s.title as string);

  const handleDelete = async () => {
    setState("deleting");
    try {
      await fetch(`/api/products/${product.id}`, { method: "DELETE" });
      onDelete();
    } catch {
      setState("idle");
    }
  };

  const handleRescrape = async () => {
    setState("scraping");
    try {
      const res = await fetch("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: product.url, force_refresh: true }),
      });
      if (res.ok) {
        onRescrape();
      }
    } finally {
      setState("idle");
    }
  };

  return (
    <div className={`bg-gray-900 border rounded-xl p-5 flex flex-col gap-3 transition-colors group ${
      isStale ? "border-yellow-800/60" : "border-gray-800 hover:border-gray-600"
    }`}>
      {/* Stale data warning */}
      {isStale && (
        <div className="flex items-center justify-between bg-yellow-900/30 border border-yellow-800/50 rounded-lg px-3 py-2">
          <p className="text-xs text-yellow-400">Low confidence — click Re-scrape to refresh</p>
          <button
            onClick={handleRescrape}
            disabled={state !== "idle"}
            className="text-xs text-yellow-300 hover:text-white bg-yellow-800/50 hover:bg-yellow-700/60 px-2 py-1 rounded transition-colors disabled:opacity-40 shrink-0 ml-2"
          >
            {state === "scraping" ? "Scraping…" : "Re-scrape"}
          </button>
        </div>
      )}

      {/* Title + stock badge */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-white text-sm leading-snug line-clamp-2">
          {(s.title as string) || product.title}
        </h3>
        <span
          className={`text-xs px-2 py-0.5 rounded-full border shrink-0 ${stockStyle}`}
        >
          {(s.stock_status as string)?.replace("_", " ") || "unknown"}
        </span>
      </div>

      {/* Price + sentiment */}
      <div className="flex items-center justify-between">
        <span className="text-blue-400 font-mono text-sm font-semibold">
          {(s.price as string) || product.price || "—"}
        </span>
        <span className={`text-xs ${sentimentColor}`}>
          ● {(s.sentiment as string) || "neutral"}
        </span>
      </div>

      {/* Why Buy — the key agent signal */}
      {s.why_buy && (
        <div className="bg-gray-800/80 rounded-lg p-3">
          <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">
            Why Buy
          </p>
          <p className="text-sm text-gray-200 italic">"{s.why_buy as string}"</p>
        </div>
      )}

      {/* Intent tag */}
      {s.best_for_intent && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-500">Best for:</span>
          <span className="text-xs bg-blue-900/60 text-blue-300 border border-blue-800 px-2 py-0.5 rounded-full">
            {s.best_for_intent as string}
          </span>
        </div>
      )}

      {/* Confidence bar */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500 shrink-0">Confidence</span>
        <div className="flex-1 bg-gray-800 rounded-full h-1.5">
          <div
            className="bg-blue-500 h-1.5 rounded-full transition-all"
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
        <span className="text-xs text-gray-400 shrink-0">
          {Math.round(confidence * 100)}%
        </span>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-gray-800">
        <a
          href={product.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-400 hover:text-blue-300 truncate max-w-[140px] transition-colors"
          title={product.url}
        >
          {safeHostname(product.url)}
        </a>
        <div className="flex items-center gap-3">
          {!isStale && (
            <button
              onClick={handleRescrape}
              disabled={state !== "idle"}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-40"
            >
              {state === "scraping" ? "scraping…" : "re-scrape"}
            </button>
          )}
          <button
            onClick={handleDelete}
            disabled={state !== "idle"}
            className="text-xs text-gray-600 hover:text-red-400 transition-colors disabled:opacity-40"
          >
            {state === "deleting" ? "removing…" : "remove"}
          </button>
        </div>
      </div>
    </div>
  );
}
