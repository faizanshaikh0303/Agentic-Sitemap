"use client";

import { useState } from "react";

const SAMPLE_QUESTIONS = [
  "What's the best budget option for someone just starting out?",
  "I need a gift under $50 — what do you recommend?",
  "Which product has the best reviews?",
  "What makes these products different from competitors?",
];

interface CompareResult {
  question: string;
  without_context: {
    answer: string;
    tokens_used: number;
    label: string;
  };
  with_context: {
    answer: string;
    tokens_used: number;
    label: string;
  };
}

export default function ComparePanel() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const runComparison = async (q: string) => {
    if (!q.trim()) return;
    setIsLoading(true);
    setError("");
    setResult(null);

    try {
      const res = await fetch("/api/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q.trim() }),
      });

      const data = await res.json();
      if (res.ok) {
        setResult(data);
        setQuestion(q);
      } else {
        setError(data.detail || "Comparison failed.");
      }
    } catch {
      setError("Cannot reach the backend. Is it running on :8000?");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-white">The Proof Layer</h2>
        <p className="text-sm text-gray-400 mt-1">
          The same question, asked twice — once with no context, once with your
          Agentic Sitemap injected into the system prompt. This is the demo
          moment.
        </p>
      </div>

      {/* Query input */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-3">
        <div className="flex gap-3">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runComparison(question)}
            placeholder="Ask anything about the products you've indexed…"
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
          <button
            onClick={() => runComparison(question)}
            disabled={!question.trim() || isLoading}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed px-6 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap"
          >
            {isLoading ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Comparing…
              </span>
            ) : (
              "Run Comparison →"
            )}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-500">Try:</span>
          {SAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => { setQuestion(q); runComparison(q); }}
              disabled={isLoading}
              className="text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 px-3 py-1.5 rounded-full text-gray-400 hover:text-gray-200 transition-colors disabled:opacity-40"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-900/40 border border-red-800 rounded-xl p-4 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Side-by-side results */}
      {result && (
        <div className="space-y-4">
          <p className="text-sm text-gray-400">
            Question:{" "}
            <span className="text-white font-medium">"{result.question}"</span>
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Without context */}
            <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-700 bg-gray-950 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-red-400">
                    Without Agentic Sitemap
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Baseline — general knowledge only
                  </p>
                </div>
                <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full">
                  {result.without_context.tokens_used} tok
                </span>
              </div>
              <div className="p-5">
                <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                  {result.without_context.answer}
                </p>
              </div>
            </div>

            {/* With context */}
            <div className="bg-gray-900 border border-blue-800/60 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-blue-800/60 bg-blue-950/40 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-blue-400">
                    With Agentic Sitemap
                  </p>
                  <p className="text-xs text-blue-300/60 mt-0.5">
                    Agent-first — product catalog injected
                  </p>
                </div>
                <span className="text-xs text-blue-400/70 bg-blue-900/40 px-2 py-0.5 rounded-full">
                  {result.with_context.tokens_used} tok
                </span>
              </div>
              <div className="p-5">
                <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">
                  {result.with_context.answer}
                </p>
              </div>
            </div>
          </div>

          {/* Insight callout */}
          <div className="bg-blue-950/30 border border-blue-800/40 rounded-xl p-4">
            <p className="text-sm text-blue-300">
              <span className="font-semibold">What you're seeing:</span> The
              left response is generic and vague — it has no product data. The
              right response cites specific products, prices, and direct buy
              links because the agent-map.json was injected into its system
              prompt. This is the core value of the Agentic Sitemap.
            </p>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!result && !isLoading && !error && (
        <div className="border border-dashed border-gray-700 rounded-xl p-10 text-center">
          <div className="text-5xl mb-4 select-none">⚡</div>
          <p className="text-gray-300 font-semibold text-lg">
            Before vs. After
          </p>
          <p className="text-sm text-gray-500 mt-3 max-w-md mx-auto leading-relaxed">
            Left panel: what an AI says with zero product context — vague,
            unhelpful, no links. Right panel: what it says after reading your
            Agentic Sitemap — specific products, real prices, direct buy URLs.
          </p>
          <p className="text-xs text-gray-600 mt-4">
            You need at least one indexed product + a generated sitemap to run
            this.
          </p>
        </div>
      )}
    </div>
  );
}
