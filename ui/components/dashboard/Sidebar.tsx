"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, List, Settings } from "lucide-react";
import { AmbientPlayer } from "./AmbientPlayer";

const NAV_ITEMS = [
  { href: "/", icon: LayoutDashboard, label: "Home" },
  { href: "/claims", icon: List, label: "Claims" },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="flex h-full w-[44px] flex-shrink-0 flex-col items-center justify-between py-3"
      style={{
        background: "rgba(10, 9, 8, 0.95)",
        borderRight: "1px solid rgba(217, 119, 6, 0.06)",
      }}
    >
      {/* Top: logo + nav */}
      <div className="flex flex-col items-center gap-4">
        {/* Logo */}
        <Link href="/" className="flex items-center justify-center" aria-label="Tensory home">
          <div
            className="flex h-6 w-6 items-center justify-center rounded text-[0.65rem] font-black"
            style={{
              background: "linear-gradient(135deg, #d97706, #ea580c)",
              color: "#0a0908",
              boxShadow: "0 0 12px rgba(217, 119, 6, 0.35)",
            }}
          >
            T
          </div>
        </Link>

        {/* Navigation */}
        <nav className="flex flex-col items-center gap-1">
          {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
            const isActive =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-label={label}
                className="flex h-7 w-7 items-center justify-center rounded transition-colors"
                style={
                  isActive
                    ? {
                        background: "rgba(217, 119, 6, 0.1)",
                        border: "1px solid rgba(217, 119, 6, 0.2)",
                      }
                    : { border: "1px solid transparent" }
                }
              >
                <Icon
                  size={15}
                  style={{ color: isActive ? "#d97706" : "#6b6560" }}
                />
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom: ambient music + settings */}
      <div className="flex flex-col items-center gap-2">
        <AmbientPlayer />
        <Link
          href="/settings"
          aria-label="Settings"
          className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:brightness-125"
        >
          <Settings size={14} style={{ color: "#4a4540" }} />
        </Link>
      </div>
    </aside>
  );
}
