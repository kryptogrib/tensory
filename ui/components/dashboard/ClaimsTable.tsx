"use client";

import { useState, useCallback, Fragment } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getExpandedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type ExpandedState,
  type Row,
} from "@tanstack/react-table";
import { formatDistanceToNow } from "date-fns";
import { ChevronDown, ChevronRight, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { useClaimDetail } from "@/hooks/use-claims";
import type { Claim, ClaimType } from "@/lib/types";

/* ─── Type badge colors (Ember palette) ─── */

const TYPE_STYLES: Record<ClaimType, string> = {
  fact: "bg-[rgba(217,119,6,0.08)] text-[#d97706] border-[rgba(217,119,6,0.15)]",
  opinion:
    "bg-[rgba(180,83,9,0.08)] text-[#b45309] border-[rgba(180,83,9,0.15)]",
  observation:
    "bg-[rgba(234,88,12,0.08)] text-[#ea580c] border-[rgba(234,88,12,0.15)]",
  experience:
    "bg-[rgba(163,230,53,0.08)] text-[#a3e635] border-[rgba(163,230,53,0.15)]",
};

/* ─── Salience bar ─── */

function SalienceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1.5 rounded-full"
        style={{
          width: `${pct}%`,
          minWidth: pct > 0 ? 4 : 0,
          background: "linear-gradient(90deg, #b45309, #d97706, #fbbf24)",
        }}
      />
      <span className="text-[0.7rem] tabular-nums" style={{ color: "#8a7e72" }}>
        {value.toFixed(2)}
      </span>
    </div>
  );
}

/* ─── Expanded row detail ─── */

function ExpandedRow({
  claim,
  onEntityClick,
}: {
  claim: Claim;
  onEntityClick: (entity: string) => void;
}) {
  const { data: detail, isLoading } = useClaimDetail(claim.id);

  return (
    <div
      className="space-y-3 px-4 py-3 text-[0.7rem]"
      style={{ background: "rgba(217, 119, 6, 0.02)" }}
    >
      {/* Full text */}
      <div>
        <span className="uppercase tracking-wider" style={{ color: "#6b6560" }}>
          full text
        </span>
        <p className="mt-1" style={{ color: "#f5e6d3" }}>
          {claim.text}
        </p>
      </div>

      {/* Episode raw text */}
      {detail?.episode && (
        <div>
          <span className="uppercase tracking-wider" style={{ color: "#6b6560" }}>
            episode
          </span>
          <p className="mt-1 whitespace-pre-wrap text-[0.65rem]" style={{ color: "#8a7e72" }}>
            {detail.episode.raw_text.slice(0, 500)}
            {detail.episode.raw_text.length > 500 && "..."}
          </p>
          {detail.episode.source && (
            <p className="mt-0.5 text-[0.6rem]" style={{ color: "#4a4540" }}>
              source: {detail.episode.source}
            </p>
          )}
        </div>
      )}

      {/* Collisions */}
      <div>
        <span className="uppercase tracking-wider" style={{ color: "#6b6560" }}>
          collisions
        </span>
        {isLoading ? (
          <p className="mt-1" style={{ color: "#4a4540" }}>
            loading...
          </p>
        ) : detail && detail.collisions.length > 0 ? (
          <ul className="mt-1 space-y-1">
            {detail.collisions.map((c, i) => (
              <li key={i} style={{ color: "#fca5a5" }}>
                {c.type} (score: {c.score.toFixed(2)}) — {c.shared_entities.join(", ")}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1" style={{ color: "#4a4540" }}>
            No collisions detected
          </p>
        )}
      </div>

      {/* Waypoints */}
      {detail && detail.waypoints.length > 0 && (
        <div>
          <span className="uppercase tracking-wider" style={{ color: "#6b6560" }}>
            linked claims ({detail.waypoints.length})
          </span>
          <ul className="mt-1 space-y-0.5">
            {detail.waypoints.map((w) => (
              <li key={w} style={{ color: "#8a7e72" }}>
                <span style={{ color: "#d97706", opacity: 0.5 }}>⟶</span>{" "}
                <span className="text-[0.6rem]" style={{ color: "#6b6560", fontFamily: "monospace" }}>{w}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Related entity relations */}
      {detail && detail.related_entities.length > 0 && (
        <div>
          <span className="uppercase tracking-wider" style={{ color: "#6b6560" }}>
            relations
          </span>
          <ul className="mt-1 space-y-1.5">
            {detail.related_entities.map((r, i) => (
              <li key={i}>
                <div style={{ color: "#8a7e72" }}>
                  <span style={{ color: "#f5e6d3" }}>{r.from_entity}</span>
                  <span style={{ color: "#4a4540" }}>{" → "}</span>
                  <span
                    className="rounded px-1 py-0.5 text-[0.6rem]"
                    style={{
                      background: "rgba(234, 88, 12, 0.08)",
                      color: "#ea580c",
                      border: "1px solid rgba(234, 88, 12, 0.12)",
                    }}
                  >
                    {r.rel_type}
                  </span>
                  <span style={{ color: "#4a4540" }}>{" → "}</span>
                  <span style={{ color: "#f5e6d3" }}>{r.to_entity}</span>
                  {r.confidence < 1.0 && (
                    <span className="ml-2 text-[0.55rem]" style={{ color: "#4a4540" }}>
                      conf: {r.confidence.toFixed(2)}
                    </span>
                  )}
                </div>
                {r.fact && (
                  <div className="mt-0.5 text-[0.6rem]" style={{ color: "#6b6560", paddingLeft: 8 }}>
                    &quot;{r.fact}&quot;
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Entities with click */}
      {claim.entities.length > 0 && (
        <div>
          <span className="uppercase tracking-wider" style={{ color: "#6b6560" }}>
            entities
          </span>
          <div className="mt-1 flex flex-wrap gap-1">
            {claim.entities.map((e) => (
              <button
                key={e}
                onClick={() => onEntityClick(e)}
                className="cursor-pointer rounded border px-1.5 py-0.5 text-[0.65rem] transition-colors hover:brightness-125"
                style={{
                  background: "rgba(217, 119, 6, 0.06)",
                  borderColor: "rgba(217, 119, 6, 0.12)",
                  color: "#d97706",
                }}
              >
                {e}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Metadata */}
      {claim.valid_from && (
        <div>
          <span className="uppercase tracking-wider" style={{ color: "#6b6560" }}>
            valid
          </span>
          <span className="ml-2" style={{ color: "#8a7e72" }}>
            {claim.valid_from}
            {claim.valid_to ? ` — ${claim.valid_to}` : " — present"}
          </span>
        </div>
      )}
    </div>
  );
}

/* ─── Column definitions ─── */

function buildColumns(
  onEntityClick: (entity: string) => void
): ColumnDef<Claim, unknown>[] {
  return [
    {
      id: "expander",
      header: () => null,
      size: 28,
      cell: ({ row }: { row: Row<Claim> }) => (
        <button
          onClick={(e) => {
            e.stopPropagation();
            row.toggleExpanded();
          }}
          className="cursor-pointer p-0.5"
          style={{ color: "#6b6560" }}
        >
          {row.getIsExpanded() ? (
            <ChevronDown size={12} />
          ) : (
            <ChevronRight size={12} />
          )}
        </button>
      ),
    },
    {
      accessorKey: "text",
      header: "Text",
      size: 999,
      cell: ({ row }: { row: Row<Claim> }) => {
        const text = row.original.text;
        return (
          <span
            className="text-[0.7rem]"
            style={{ color: "#f5e6d3" }}
            title={text}
          >
            {text.length > 60 ? text.slice(0, 60) + "..." : text}
          </span>
        );
      },
    },
    {
      accessorKey: "type",
      header: "Type",
      size: 100,
      cell: ({ row }: { row: Row<Claim> }) => {
        const t = row.original.type;
        return (
          <span
            className={`inline-block rounded border px-1.5 py-0.5 text-[0.6rem] ${TYPE_STYLES[t]}`}
          >
            {t}
          </span>
        );
      },
    },
    {
      accessorKey: "entities",
      header: "Entities",
      size: 150,
      enableSorting: false,
      cell: ({ row }: { row: Row<Claim> }) => {
        const ents = row.original.entities;
        if (!ents.length)
          return (
            <span className="text-[0.6rem]" style={{ color: "#4a4540" }}>
              --
            </span>
          );
        return (
          <div className="flex flex-wrap gap-0.5">
            {ents.slice(0, 3).map((e) => (
              <button
                key={e}
                onClick={(ev) => {
                  ev.stopPropagation();
                  onEntityClick(e);
                }}
                className="cursor-pointer rounded border px-1 py-0 text-[0.6rem] transition-colors hover:brightness-125"
                style={{
                  background: "rgba(217, 119, 6, 0.06)",
                  borderColor: "rgba(217, 119, 6, 0.12)",
                  color: "#d97706",
                }}
              >
                {e}
              </button>
            ))}
            {ents.length > 3 && (
              <span className="text-[0.6rem]" style={{ color: "#6b6560" }}>
                +{ents.length - 3}
              </span>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: "salience",
      header: "Salience",
      size: 120,
      cell: ({ row }: { row: Row<Claim> }) => (
        <SalienceBar value={row.original.salience} />
      ),
    },
    {
      accessorKey: "context_id",
      header: "Source",
      size: 100,
      enableSorting: false,
      cell: ({ row }: { row: Row<Claim> }) => (
        <span className="text-[0.65rem]" style={{ color: "#6b6560" }}>
          {row.original.context_id
            ? row.original.context_id.slice(0, 8)
            : "--"}
        </span>
      ),
    },
    {
      accessorKey: "created_at",
      header: "Created",
      size: 80,
      cell: ({ row }: { row: Row<Claim> }) => (
        <span className="text-[0.65rem]" style={{ color: "#6b6560" }}>
          {formatDistanceToNow(new Date(row.original.created_at), {
            addSuffix: true,
          })}
        </span>
      ),
    },
  ];
}

/* ─── Sort header icon ─── */

function SortIcon({ sorted }: { sorted: false | "asc" | "desc" }) {
  if (sorted === "asc") return <ArrowUp size={10} />;
  if (sorted === "desc") return <ArrowDown size={10} />;
  return <ArrowUpDown size={10} style={{ opacity: 0.4 }} />;
}

/* ─── Main component ─── */

export interface ClaimsTableProps {
  data: Claim[];
  total: number;
  offset: number;
  limit: number;
  sorting: SortingState;
  onSortingChange: (sorting: SortingState) => void;
  onOffsetChange: (offset: number) => void;
  onEntityClick: (entity: string) => void;
  isLoading?: boolean;
}

export function ClaimsTable({
  data,
  total,
  offset,
  limit,
  sorting,
  onSortingChange,
  onOffsetChange,
  onEntityClick,
  isLoading,
}: ClaimsTableProps) {
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const columns = buildColumns(onEntityClick);

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      expanded,
    },
    onSortingChange: (updater) => {
      const next =
        typeof updater === "function" ? updater(sorting) : updater;
      onSortingChange(next);
    },
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    manualSorting: true,
    manualPagination: true,
    rowCount: total,
  });

  const pageCount = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const showFrom = total > 0 ? offset + 1 : 0;
  const showTo = Math.min(offset + limit, total);

  const goToPage = useCallback(
    (page: number) => {
      onOffsetChange((page - 1) * limit);
    },
    [limit, onOffsetChange]
  );

  return (
    <div className="flex h-full flex-col">
      {/* Table */}
      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow
                key={hg.id}
                className="border-b hover:bg-transparent"
                style={{ borderColor: "rgba(217, 119, 6, 0.06)" }}
              >
                {hg.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead
                      key={header.id}
                      className="h-8 select-none px-2 text-[0.7rem] uppercase tracking-wider"
                      style={{
                        color: "#8a7e72",
                        width:
                          header.getSize() === 999
                            ? "auto"
                            : header.getSize(),
                        cursor: canSort ? "pointer" : "default",
                      }}
                      onClick={
                        canSort
                          ? header.column.getToggleSortingHandler()
                          : undefined
                      }
                    >
                      <div className="flex items-center gap-1">
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                        {canSort && <SortIcon sorted={sorted} />}
                      </div>
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-32 text-center text-[0.7rem]"
                  style={{ color: "#4a4540" }}
                >
                  loading claims...
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-32 text-center text-[0.7rem]"
                  style={{ color: "#4a4540" }}
                >
                  No claims found
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <Fragment key={row.id}>
                  <TableRow
                    className="cursor-pointer border-b transition-colors hover:bg-[rgba(217,119,6,0.03)]"
                    style={{
                      borderColor: "rgba(217, 119, 6, 0.06)",
                      background: "transparent",
                    }}
                    onClick={() => row.toggleExpanded()}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className="px-2 py-1.5">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                  {row.getIsExpanded() && (
                    <TableRow
                      style={{
                        borderColor: "rgba(217, 119, 6, 0.06)",
                      }}
                    >
                      <TableCell
                        colSpan={columns.length}
                        className="p-0"
                      >
                        <ExpandedRow
                          claim={row.original}
                          onEntityClick={onEntityClick}
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div
        className="flex items-center justify-between border-t px-3 py-2"
        style={{ borderColor: "rgba(217, 119, 6, 0.06)" }}
      >
        <span className="text-[0.65rem]" style={{ color: "#6b6560" }}>
          Showing {showFrom}-{showTo} of {total}
        </span>
        <div className="flex items-center gap-1">
          <button
            disabled={currentPage <= 1}
            onClick={() => goToPage(currentPage - 1)}
            className="cursor-pointer rounded px-2 py-0.5 text-[0.65rem] transition-colors disabled:cursor-default disabled:opacity-30"
            style={{
              color: "#d97706",
              border: "1px solid rgba(217, 119, 6, 0.12)",
            }}
          >
            prev
          </button>
          <span className="px-2 text-[0.65rem] tabular-nums" style={{ color: "#8a7e72" }}>
            {currentPage} / {pageCount}
          </span>
          <button
            disabled={currentPage >= pageCount}
            onClick={() => goToPage(currentPage + 1)}
            className="cursor-pointer rounded px-2 py-0.5 text-[0.65rem] transition-colors disabled:cursor-default disabled:opacity-30"
            style={{
              color: "#d97706",
              border: "1px solid rgba(217, 119, 6, 0.12)",
            }}
          >
            next
          </button>
        </div>
      </div>
    </div>
  );
}
