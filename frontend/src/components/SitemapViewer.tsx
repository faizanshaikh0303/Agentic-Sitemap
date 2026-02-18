"use client";

import { useState } from "react";

interface SitemapData {
  llms_txt: string;
  agent_map: unknown;
}

interface SitemapViewerProps {
  sitemap: SitemapData | null;
  onGenerate: () => void;
  isLoading: boolean;
}

export default function SitemapViewer({
  sitemap,
  onGenerate,
  isLoading,
}: SitemapViewerProps) {
  const [view, setView] = useState<"llms" | "json">("llms");
  const [copied, setCopied] = useState(false);

  const content =
    view === "llms"
      ? sitemap?.llms_txt ?? ""
      : JSON.stringify(sitemap?.agent_map, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!sitemap) {
    return (
      <div className="flex flex-col items-center justify-center py-28 gap-6">
        <div className="text-6xl select-none">🗺️</div>
        <div className="text-center">
          <p className="text-xl font-semibold text-gray-200">
            No sitemap generated yet
          </p>
          <p className="text-sm text-gray-500 mt-2">
            Index at least one product, then click generate.
          </p>
        </div>
        <button
          onClick={onGenerate}
          disabled={isLoading}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-6 py-3 rounded-lg font-medium transition-colors"
        >
          {isLoading ? "Generating…" : "Generate llms.txt →"}
        </button>
        <div className="max-w-lg text-center">
          <p className="text-xs text-gray-500 leading-relaxed">
            The generator creates two files:{" "}
            <code className="text-blue-400">llms.txt</code> (human-readable,
            markdown) and{" "}
            <code className="text-blue-400">agent-map.json</code> (structured,
            for programmatic injection). Serve{" "}
            <code className="text-blue-400">llms.txt</code> at the root of your
            domain so AI agents can discover it automatically.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">
            Generated Sitemap
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Serve this at{" "}
            <code className="text-blue-400 bg-gray-800 px-1.5 py-0.5 rounded text-xs">
              yoursite.com/llms.txt
            </code>{" "}
            so AI agents can auto-discover it. The JSON version is for
            programmatic injection into system prompts.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={onGenerate}
            disabled={isLoading}
            className="text-sm bg-gray-800 hover:bg-gray-700 disabled:opacity-40 px-4 py-2 rounded-lg transition-colors"
          >
            {isLoading ? "Regenerating…" : "Regenerate"}
          </button>
          <button
            onClick={handleCopy}
            className="text-sm bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded-lg transition-colors min-w-[70px]"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
      </div>

      {/* View toggle */}
      <div className="flex gap-1 bg-gray-800 p-1 rounded-lg w-fit">
        {(
          [
            { id: "llms", label: "llms.txt" },
            { id: "json", label: "agent-map.json" },
          ] as const
        ).map((v) => (
          <button
            key={v.id}
            onClick={() => setView(v.id)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              view === v.id
                ? "bg-gray-700 text-white"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Code viewer */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {/* Fake macOS chrome */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800 bg-gray-950">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-500/70" />
            <div className="w-3 h-3 rounded-full bg-yellow-500/70" />
            <div className="w-3 h-3 rounded-full bg-green-500/70" />
          </div>
          <span className="text-xs text-gray-500 ml-2 font-mono">
            {view === "llms" ? "llms.txt" : "agent-map.json"}
          </span>
          <span className="ml-auto text-xs text-gray-600">
            {content.length.toLocaleString()} chars
          </span>
        </div>

        <pre className="p-6 text-sm text-gray-300 font-mono overflow-x-auto max-h-[600px] overflow-y-auto leading-relaxed whitespace-pre-wrap">
          {content}
        </pre>
      </div>
    </div>
  );
}
