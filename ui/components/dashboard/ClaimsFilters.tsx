"use client";

import { Search, X } from "lucide-react";
import type { ClaimType } from "@/lib/types";

const CLAIM_TYPES: ClaimType[] = ["fact", "opinion", "observation", "experience"];

const TYPE_STYLES: Record<ClaimType, { active: string; inactive: string }> = {
  fact: {
    active: "bg-[rgba(217,119,6,0.12)] text-[#d97706] border-[rgba(217,119,6,0.25)]",
    inactive: "bg-transparent text-[#6b6560] border-[rgba(217,119,6,0.08)]",
  },
  opinion: {
    active: "bg-[rgba(180,83,9,0.12)] text-[#b45309] border-[rgba(180,83,9,0.25)]",
    inactive: "bg-transparent text-[#6b6560] border-[rgba(180,83,9,0.08)]",
  },
  observation: {
    active: "bg-[rgba(234,88,12,0.12)] text-[#ea580c] border-[rgba(234,88,12,0.25)]",
    inactive: "bg-transparent text-[#6b6560] border-[rgba(234,88,12,0.08)]",
  },
  experience: {
    active: "bg-[rgba(163,230,53,0.12)] text-[#a3e635] border-[rgba(163,230,53,0.25)]",
    inactive: "bg-transparent text-[#6b6560] border-[rgba(163,230,53,0.08)]",
  },
};

export interface ClaimsFiltersProps {
  search: string;
  onSearchChange: (v: string) => void;
  selectedTypes: ClaimType[];
  onTypesChange: (types: ClaimType[]) => void;
  entity: string;
  onEntityChange: (v: string) => void;
  minSalience: string;
  onMinSalienceChange: (v: string) => void;
  maxSalience: string;
  onMaxSalienceChange: (v: string) => void;
}

export function ClaimsFilters({
  search,
  onSearchChange,
  selectedTypes,
  onTypesChange,
  entity,
  onEntityChange,
  minSalience,
  onMinSalienceChange,
  maxSalience,
  onMaxSalienceChange,
}: ClaimsFiltersProps) {
  function toggleType(t: ClaimType) {
    if (selectedTypes.includes(t)) {
      onTypesChange(selectedTypes.filter((x) => x !== t));
    } else {
      onTypesChange([...selectedTypes, t]);
    }
  }

  return (
    <div
      className="flex flex-wrap items-center gap-3 px-3 py-2"
      style={{
        borderBottom: "1px solid rgba(217, 119, 6, 0.06)",
      }}
    >
      {/* Search */}
      <div
        className="flex items-center gap-1.5 rounded px-2 py-1"
        style={{
          border: "1px solid rgba(217, 119, 6, 0.1)",
          background: "rgba(217, 119, 6, 0.02)",
        }}
      >
        <Search size={11} style={{ color: "#6b6560" }} />
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="search claims..."
          className="w-36 bg-transparent text-[0.7rem] outline-none placeholder:text-[#4a4540]"
          style={{ color: "#f5e6d3" }}
        />
        {search && (
          <button
            onClick={() => onSearchChange("")}
            className="cursor-pointer"
            style={{ color: "#6b6560" }}
          >
            <X size={10} />
          </button>
        )}
      </div>

      {/* Separator */}
      <div className="h-4 w-px" style={{ background: "rgba(217, 119, 6, 0.08)" }} />

      {/* Type toggles */}
      <div className="flex items-center gap-1">
        {CLAIM_TYPES.map((t) => {
          const isActive = selectedTypes.includes(t);
          const style = TYPE_STYLES[t];
          return (
            <button
              key={t}
              onClick={() => toggleType(t)}
              className={`cursor-pointer rounded border px-1.5 py-0.5 text-[0.6rem] transition-colors ${
                isActive ? style.active : style.inactive
              }`}
            >
              {t}
            </button>
          );
        })}
      </div>

      {/* Separator */}
      <div className="h-4 w-px" style={{ background: "rgba(217, 119, 6, 0.08)" }} />

      {/* Entity filter */}
      <div
        className="flex items-center gap-1.5 rounded px-2 py-1"
        style={{
          border: "1px solid rgba(217, 119, 6, 0.1)",
          background: "rgba(217, 119, 6, 0.02)",
        }}
      >
        <input
          type="text"
          value={entity}
          onChange={(e) => onEntityChange(e.target.value)}
          placeholder="entity..."
          className="w-20 bg-transparent text-[0.7rem] outline-none placeholder:text-[#4a4540]"
          style={{ color: "#f5e6d3" }}
        />
        {entity && (
          <button
            onClick={() => onEntityChange("")}
            className="cursor-pointer"
            style={{ color: "#6b6560" }}
          >
            <X size={10} />
          </button>
        )}
      </div>

      {/* Separator */}
      <div className="h-4 w-px" style={{ background: "rgba(217, 119, 6, 0.08)" }} />

      {/* Salience range */}
      <div className="flex items-center gap-1 text-[0.65rem]" style={{ color: "#6b6560" }}>
        <span>sal</span>
        <input
          type="text"
          value={minSalience}
          onChange={(e) => onMinSalienceChange(e.target.value)}
          placeholder="0"
          className="w-8 rounded bg-transparent px-1 py-0.5 text-center text-[0.65rem] outline-none"
          style={{
            border: "1px solid rgba(217, 119, 6, 0.1)",
            color: "#f5e6d3",
          }}
        />
        <span>-</span>
        <input
          type="text"
          value={maxSalience}
          onChange={(e) => onMaxSalienceChange(e.target.value)}
          placeholder="1"
          className="w-8 rounded bg-transparent px-1 py-0.5 text-center text-[0.65rem] outline-none"
          style={{
            border: "1px solid rgba(217, 119, 6, 0.1)",
            color: "#f5e6d3",
          }}
        />
      </div>
    </div>
  );
}
