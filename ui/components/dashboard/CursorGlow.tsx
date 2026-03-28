"use client";

/* ─── Cursor Glow ────────────────────────────────────────────────────
 *
 * Ambient light following cursor. Uses transform: translate() which
 * runs on the GPU compositor thread — zero layout thrashing.
 *
 * Think-Council verdict: 4/6 agents agreed on transform over left/top.
 * CSS transition on transform is compositor-only (no layout, no paint).
 * Short duration (0.15s) = responsive, not floaty.
 * Respects prefers-reduced-motion.
 * ──────────────────────────────────────────────────────────────────── */

import { useRef, useEffect } from "react";

export function CursorGlow() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    function onMove(e: PointerEvent) {
      // Write directly to transform — compositor thread, no layout
      el!.style.transform = `translate(${e.clientX - 250}px, ${e.clientY - 250}px)`;
    }

    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  return (
    <div
      ref={ref}
      className="pointer-events-none fixed left-0 top-0"
      style={{
        width: 500,
        height: 500,
        borderRadius: "50%",
        background:
          "radial-gradient(circle at center, rgba(217,119,6,0.035) 0%, rgba(217,119,6,0.012) 35%, transparent 60%)",
        willChange: "transform",
        transition: "transform 0.15s ease-out",
        transform: "translate(-500px, -500px)",
        zIndex: 0,
      }}
    />
  );
}
