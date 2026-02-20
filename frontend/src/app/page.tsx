"use client";

import { useCallback, useEffect, useState } from "react";
import ComparePanel from "@/components/ComparePanel";
import ProductCard from "@/components/ProductCard";
import ScrapeForm from "@/components/ScrapeForm";
import SitemapViewer from "@/components/SitemapViewer";

type Tab = "products" | "sitemap" | "proof";

interface SitemapData {
  llms_txt: string;
  agent_map: unknown;
}

interface Product {
  id: number;
  url: string;
  title: string;
  price?: string;
  summary?: Record<string, unknown>;
}

const TABS = [
  { id: "products" as Tab, step: "①", label: "Products", sub: "Scrape & Index" },
  { id: "sitemap" as Tab, step: "②", label: "Sitemap", sub: "llms.txt Output" },
  { id: "proof" as Tab, step: "③", label: "Proof Layer", sub: "Before vs After" },
];

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("products");
  const [products, setProducts] = useState<Product[]>([]);
  const [sitemap, setSitemap] = useState<SitemapData | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState("");

  const fetchProducts = useCallback(async () => {
    try {
      const res = await fetch("/api/products");
      if (res.ok) {
        const data = await res.json();
        setProducts(data.products ?? []);
      }
    } catch {
      // backend not reachable yet — silently ignore
    }
  }, []);

  const handleGenerate = useCallback(async () => {
    setIsGenerating(true);
    setGenerateError("");
    try {
      const res = await fetch("/api/generate", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        setSitemap({
          llms_txt: data.llms_txt_preview,
          agent_map: data.agent_map,
        });
        setActiveTab("sitemap");
      } else {
        setGenerateError(data.detail || "Generation failed.");
      }
    } catch {
      setGenerateError("Cannot reach the backend.");
    } finally {
      setIsGenerating(false);
    }
  }, []);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="border-b border-gray-800 px-6 md:px-8 py-5 sticky top-0 z-10 bg-gray-950/90 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl md:text-2xl font-bold text-white tracking-tight">
              <span className="text-blue-400 mr-1">⟨/⟩</span>
              Agentic Sitemap
            </h1>
            <p className="text-xs text-gray-500 mt-0.5 hidden sm:block">
              Product pages → AI-ready intelligence layers → llms.txt
            </p>
          </div>

          <div className="flex items-center gap-3">
            {products.length > 0 && (
              <span className="text-xs text-gray-400 bg-gray-800 border border-gray-700 px-3 py-1 rounded-full">
                {products.length} indexed
              </span>
            )}
            <button
              onClick={handleGenerate}
              disabled={products.length === 0 || isGenerating}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap"
            >
              {isGenerating ? "Generating…" : "Generate llms.txt →"}
            </button>
          </div>
        </div>

        {generateError && (
          <div className="max-w-7xl mx-auto mt-2">
            <p className="text-xs text-red-400">{generateError}</p>
          </div>
        )}
      </header>

      {/* ── Tab bar ────────────────────────────────────────────────────────── */}
      <div className="border-b border-gray-800 bg-gray-950">
        <div className="max-w-7xl mx-auto px-6 md:px-8 flex gap-0.5 pt-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 md:px-5 py-3 text-sm font-medium rounded-t-lg transition-colors flex items-center gap-2 ${
                activeTab === tab.id
                  ? "bg-gray-900 text-white border-b-2 border-blue-500"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-900/50"
              }`}
            >
              <span className="text-blue-400/80">{tab.step}</span>
              {tab.label}
              <span className="hidden md:inline text-xs text-gray-500">
                {tab.sub}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <div className="max-w-7xl mx-auto px-6 md:px-8 py-8">
        {/* Products tab */}
        {activeTab === "products" && (
          <div className="space-y-8">
            <ScrapeForm onProductAdded={fetchProducts} />

            {products.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-center">
                <div className="text-6xl mb-4 select-none">📦</div>
                <p className="text-lg font-semibold text-gray-300">
                  No products indexed yet
                </p>
                <p className="text-sm text-gray-500 mt-2 max-w-sm">
                  Paste a product URL above. The scraper extracts structured
                  signals; Groq generates the agent-ready summary — all stored
                  in Postgres.
                </p>
              </div>
            ) : (
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-base font-semibold text-gray-300">
                    Indexed Products
                    <span className="ml-2 text-sm font-normal text-gray-500">
                      ({products.length})
                    </span>
                  </h2>
                  <button
                    onClick={handleGenerate}
                    disabled={isGenerating}
                    className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                  >
                    {isGenerating ? "Generating…" : "Generate sitemap →"}
                  </button>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {products.map((product) => (
                    <ProductCard
                      key={product.id}
                      product={product}
                      onRescrape={fetchProducts}
                      onDelete={fetchProducts}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Sitemap tab */}
        {activeTab === "sitemap" && (
          <SitemapViewer
            sitemap={sitemap}
            onGenerate={handleGenerate}
            isLoading={isGenerating}
          />
        )}

        {/* Proof Layer tab */}
        {activeTab === "proof" && <ComparePanel />}
      </div>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="border-t border-gray-800 mt-16 px-8 py-6 text-center">
        <p className="text-xs text-gray-600">
          Agentic Sitemap MVP — Python + FastAPI + Groq + Next.js + PostgreSQL
        </p>
      </footer>
    </main>
  );
}
