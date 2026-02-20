"use client";

import { useState } from "react";

const DEMO_URLS = [
  "https://www.nike.com/t/vomero-premium-road-running-shoes-l11miwwa/IQ4035-100",
  "https://getlivfresh.com/products/dental-gel-toothpaste-wintergreen?_gl=1*aw7tie*_up*MQ..*_gs*MQ..&gclid=Cj0KCQiAqeDMBhDcARIsAJEbU9QEbsECAarMcCPT2diHY2TkcszUVN1wunmo0oBFSuw_gRDnFnTCmF8aAtWBEALw_wcB&gbraid=0AAAAADfS9OBcWOOM8Feni9L9dF_sEstlD",
  "https://travelpro.com/products/platinum%C2%AE-elite-25-expandable-spinner?variant=19631913992290",
];

function safeHostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

interface ScrapeFormProps {
  onProductAdded: () => void;
}

export default function ScrapeForm({ onProductAdded }: ScrapeFormProps) {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  const handleSubmit = async (targetUrl: string) => {
    if (!targetUrl.trim()) return;

    setStatus("loading");
    setMessage("");

    try {
      const res = await fetch("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: targetUrl.trim() }),
      });

      const data = await res.json();

      if (res.ok) {
        const title = data.product?.title || "Product";
        setStatus("success");
        setMessage(
          data.status === "cached"
            ? `Already indexed: "${title}"`
            : `Indexed: "${title}"`
        );
        setUrl("");
        onProductAdded();
      } else {
        setStatus("error");
        setMessage(data.detail || "Indexing failed.");
      }
    } catch {
      setStatus("error");
      setMessage("Cannot reach the backend. Is it running on :8000?");
    }

    setTimeout(() => setStatus("idle"), 4000);
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-1">
        Step 1 — Index a Product Page
      </h2>
      <p className="text-sm text-gray-400 mb-4">
        Paste any shoppable product URL. The scraper strips noise and extracts
        structured signals; Groq generates the agent-ready summary.
      </p>

      <div className="flex gap-3">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit(url)}
          placeholder="https://yourstore.com/products/amazing-thing"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
        />
        <button
          onClick={() => handleSubmit(url)}
          disabled={!url.trim() || status === "loading"}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed px-6 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap"
        >
          {status === "loading" ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Indexing…
            </span>
          ) : (
            "Scrape + Index →"
          )}
        </button>
      </div>

      {message && (
        <p
          className={`mt-2 text-sm ${
            status === "success" ? "text-green-400" : "text-red-400"
          }`}
        >
          {message}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-xs text-gray-500">Try a demo URL:</span>
        {DEMO_URLS.map((demoUrl) => (
          <button
            key={demoUrl}
            onClick={() => handleSubmit(demoUrl)}
            disabled={status === "loading"}
            className="text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 px-3 py-1.5 rounded-full text-gray-400 hover:text-gray-200 transition-colors disabled:opacity-40"
          >
            {safeHostname(demoUrl)}
          </button>
        ))}
      </div>
    </div>
  );
}
