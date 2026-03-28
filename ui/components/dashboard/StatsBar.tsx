"use client";

import { useStats } from "@/hooks/use-stats";
import { HudWindow } from "./HudWindow";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

function LoadingSkeleton() {
  return (
    <div className="flex items-center gap-4 px-4 py-2.5">
      {[1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="h-3 w-16 animate-pulse rounded"
          style={{ background: "rgba(217, 119, 6, 0.15)" }}
        />
      ))}
    </div>
  );
}

function SearchBox() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);
  const [query, setQuery] = useState("");

  // ⌘K / Ctrl+K hotkey
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === "Escape") {
        inputRef.current?.blur();
        setQuery("");
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (query.trim()) {
        router.push(`/claims?search=${encodeURIComponent(query.trim())}`);
        inputRef.current?.blur();
      }
    },
    [query, router],
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="ml-4 flex flex-shrink-0 items-center gap-2 rounded-md px-3 py-1.5"
      style={{
        border: `1px solid rgba(217, 119, 6, ${focused ? 0.25 : 0.1})`,
        background: focused ? "rgba(217, 119, 6, 0.03)" : "transparent",
        transition: "border-color 0.2s, background 0.2s",
        minWidth: 200,
      }}
    >
      <svg
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        stroke={focused ? "#8a7e72" : "#4a4540"}
        strokeWidth="1.2"
      >
        <circle cx="5" cy="5" r="3.5" />
        <line x1="7.5" y1="7.5" x2="10.5" y2="10.5" />
      </svg>
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder="search claims..."
        className="flex-1 bg-transparent text-[0.7rem] outline-none"
        style={{
          color: "#f5e6d3",
          fontFamily: "'SF Mono', Monaco, monospace",
          caretColor: "#d97706",
        }}
      />
      {!focused && !query && (
        <kbd
          className="rounded px-1.5 py-0.5 text-[0.55rem]"
          style={{
            background: "rgba(217, 119, 6, 0.06)",
            color: "#4a4540",
            border: "1px solid rgba(217, 119, 6, 0.08)",
          }}
        >
          ⌘K
        </kbd>
      )}
    </form>
  );
}

export function StatsBar() {
  const { data, isLoading, isError } = useStats();

  if (isLoading) {
    return (
      <HudWindow>
        <LoadingSkeleton />
      </HudWindow>
    );
  }

  if (isError || !data) {
    return (
      <HudWindow>
        <div className="px-4 py-2.5 text-[0.7rem]" style={{ color: "#fca5a5" }}>
          $ API unreachable
        </div>
      </HudWindow>
    );
  }

  const totalClaims = data.counts?.claims ?? 0;
  const entities = data.counts?.entities ?? 0;
  const collisions = data.counts?.collisions ?? 0;
  const avgSalience = data.avg_salience ?? 0;

  return (
    <HudWindow>
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-1 overflow-x-auto text-[0.8rem]">
          {/* Prompt symbol */}
          <span style={{ color: "#4a4540" }}>$</span>

          {/* Claims */}
          <span className="ml-2" style={{ color: "#8a7e72" }}>
            claims
          </span>
          <span className="font-bold" style={{ color: "#f5e6d3" }}>
            {formatNumber(totalClaims)}
          </span>

          <span className="mx-2" style={{ color: "#4a4540" }}>
            |
          </span>

          {/* Salience */}
          <span style={{ color: "#8a7e72" }}>salience</span>
          <span className="font-bold" style={{ color: "#f5e6d3" }}>
            {avgSalience.toFixed(2)}
          </span>

          <span className="mx-2" style={{ color: "#4a4540" }}>
            |
          </span>

          {/* Entities */}
          <span style={{ color: "#8a7e72" }}>entities</span>
          <span className="font-bold" style={{ color: "#f5e6d3" }}>
            {formatNumber(entities)}
          </span>

          <span className="mx-2" style={{ color: "#4a4540" }}>
            |
          </span>

          {/* Collisions */}
          <span style={{ color: "#8a7e72" }}>collisions</span>
          <span className="font-bold" style={{ color: "#fca5a5" }}>
            {formatNumber(collisions)}
          </span>
        </div>

        {/* Search — functional with ⌘K hotkey */}
        <SearchBox />
      </div>
    </HudWindow>
  );
}
