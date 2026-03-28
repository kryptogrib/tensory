"use client";

import { Suspense, useState, useCallback, useMemo, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import type { SortingState } from "@tanstack/react-table";
import { StatsBar } from "@/components/dashboard/StatsBar";
import { ClaimsTable } from "@/components/dashboard/ClaimsTable";
import { ClaimsFilters } from "@/components/dashboard/ClaimsFilters";
import { useClaims, useSearch } from "@/hooks/use-claims";
import type { ClaimType } from "@/lib/types";

const PAGE_SIZE = 25;

export default function ClaimsPage() {
  return (
    <Suspense
      fallback={
        <div
          className="flex h-full items-center justify-center"
          style={{ background: "#0a0908" }}
        >
          <span className="text-[0.7rem]" style={{ color: "#4a4540" }}>
            loading claims...
          </span>
        </div>
      }
    >
      <ClaimsPageInner />
    </Suspense>
  );
}

function ClaimsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  /* ─── State from URL search params ─── */
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [selectedTypes, setSelectedTypes] = useState<ClaimType[]>(() => {
    const t = searchParams.get("type");
    return t ? (t.split(",") as ClaimType[]) : [];
  });
  const [entity, setEntity] = useState(searchParams.get("entity") ?? "");
  const [minSalience, setMinSalience] = useState(
    searchParams.get("min_sal") ?? ""
  );
  const [maxSalience, setMaxSalience] = useState(
    searchParams.get("max_sal") ?? ""
  );
  const [offset, setOffset] = useState(
    Number(searchParams.get("offset")) || 0
  );
  const [sorting, setSorting] = useState<SortingState>(() => {
    const sb = searchParams.get("sort_by");
    const sd = searchParams.get("sort_dir");
    if (sb) return [{ id: sb, desc: sd === "desc" }];
    return [];
  });

  /* ─── Debounced search for full-text ─── */
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  /* ─── Sync state to URL params ─── */
  useEffect(() => {
    const params = new URLSearchParams();
    if (debouncedSearch) params.set("q", debouncedSearch);
    if (selectedTypes.length) params.set("type", selectedTypes.join(","));
    if (entity) params.set("entity", entity);
    if (minSalience) params.set("min_sal", minSalience);
    if (maxSalience) params.set("max_sal", maxSalience);
    if (offset > 0) params.set("offset", String(offset));
    if (sorting.length) {
      params.set("sort_by", sorting[0].id);
      params.set("sort_dir", sorting[0].desc ? "desc" : "asc");
    }
    const qs = params.toString();
    router.replace(`/claims${qs ? `?${qs}` : ""}`, { scroll: false });
  }, [
    debouncedSearch,
    selectedTypes,
    entity,
    minSalience,
    maxSalience,
    offset,
    sorting,
    router,
  ]);

  /* ─── API params ─── */
  const claimParams = useMemo(
    () => ({
      offset,
      limit: PAGE_SIZE,
      type: selectedTypes.length === 1 ? selectedTypes[0] : undefined,
      entity: entity || undefined,
      min_salience: minSalience ? Number(minSalience) : undefined,
      sort_by: sorting.length ? sorting[0].id : undefined,
      sort_dir: sorting.length
        ? sorting[0].desc
          ? "desc"
          : "asc"
        : undefined,
    }),
    [offset, selectedTypes, entity, minSalience, sorting]
  );

  /* ─── Data fetching ─── */
  const isSearchMode = debouncedSearch.length > 0;
  const claimsQuery = useClaims(claimParams);
  const searchQuery = useSearch(debouncedSearch, 50);

  /* ─── Resolve data ─── */
  const data = useMemo(() => {
    if (isSearchMode && searchQuery.data) {
      let results = searchQuery.data.map((r) => r.claim);
      // Client-side type filter for search results
      if (selectedTypes.length > 0) {
        results = results.filter((c) => selectedTypes.includes(c.type));
      }
      return { items: results, total: results.length, offset: 0, limit: results.length || PAGE_SIZE };
    }
    return claimsQuery.data ?? { items: [], total: 0, offset: 0, limit: PAGE_SIZE };
  }, [isSearchMode, searchQuery.data, claimsQuery.data, selectedTypes]);

  const isLoading = isSearchMode ? searchQuery.isLoading : claimsQuery.isLoading;

  /* ─── Handlers ─── */
  const handleEntityClick = useCallback((e: string) => {
    setEntity(e);
    setOffset(0);
  }, []);

  const handleSortingChange = useCallback((next: SortingState) => {
    setSorting(next);
    setOffset(0);
  }, []);

  const handleTypesChange = useCallback((types: ClaimType[]) => {
    setSelectedTypes(types);
    setOffset(0);
  }, []);

  const handleSearchChange = useCallback((v: string) => {
    setSearch(v);
    setOffset(0);
  }, []);

  const handleEntityChange = useCallback((v: string) => {
    setEntity(v);
    setOffset(0);
  }, []);

  return (
    <div className="flex h-full flex-col" style={{ background: "#0a0908" }}>
      <StatsBar />
      <ClaimsFilters
        search={search}
        onSearchChange={handleSearchChange}
        selectedTypes={selectedTypes}
        onTypesChange={handleTypesChange}
        entity={entity}
        onEntityChange={handleEntityChange}
        minSalience={minSalience}
        onMinSalienceChange={setMinSalience}
        maxSalience={maxSalience}
        onMaxSalienceChange={setMaxSalience}
      />
      <div className="flex-1 overflow-hidden">
        <ClaimsTable
          data={data.items}
          total={data.total}
          offset={data.offset}
          limit={data.limit}
          sorting={sorting}
          onSortingChange={handleSortingChange}
          onOffsetChange={setOffset}
          onEntityClick={handleEntityClick}
          isLoading={isLoading}
        />
      </div>
    </div>
  );
}
