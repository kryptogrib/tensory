"use client";

/* ─── Cursor Glow ────────────────────────────────────────────────────
 *
 * Simple, elegant: one soft radial gradient div that follows the
 * cursor via CSS transition. No JS animation loop, no lerp, no lag.
 * Just CSS doing what it does best.
 * ──────────────────────────────────────────────────────────────────── */

import { useRef, useEffect } from "react";

export function CursorGlow() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (ref.current) {
        ref.current.style.left = `${e.clientX}px`;
        ref.current.style.top = `${e.clientY}px`;
      }
    }
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  return (
    <div
      ref={ref}
      className="pointer-events-none fixed"
      style={{
        width: 600,
        height: 600,
        marginLeft: -300,
        marginTop: -300,
        borderRadius: "50%",
        background:
          "radial-gradient(circle at center, rgba(217,119,6,0.04) 0%, rgba(217,119,6,0.015) 30%, transparent 60%)",
        zIndex: 0,
        transition: "left 0.6s ease-out, top 0.6s ease-out",
        left: -600,
        top: -600,
      }}
    />
  );
}
