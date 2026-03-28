"use client";

/* ─── Cursor Glow ────────────────────────────────────────────────────
 *
 * Ambient light following the cursor. Uses CSS transition for
 * buttery-smooth movement instead of JS lerp (no stepping artifacts).
 *
 * The transition property handles all interpolation — we just set
 * the target position on pointermove and CSS does the smoothing.
 * Two layers: large soft outer + smaller brighter inner (slower).
 * ──────────────────────────────────────────────────────────────────── */

import { useRef, useEffect } from "react";

export function CursorGlow() {
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerMove(e: PointerEvent) {
      // Just set the target — CSS transition handles the smoothing
      if (outerRef.current) {
        outerRef.current.style.left = `${e.clientX - 250}px`;
        outerRef.current.style.top = `${e.clientY - 250}px`;
      }
      if (innerRef.current) {
        innerRef.current.style.left = `${e.clientX - 100}px`;
        innerRef.current.style.top = `${e.clientY - 100}px`;
      }
    }

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    return () => window.removeEventListener("pointermove", onPointerMove);
  }, []);

  return (
    <>
      {/* Outer soft glow — large, very subtle, slow follow */}
      <div
        ref={outerRef}
        className="pointer-events-none fixed"
        style={{
          width: 500,
          height: 500,
          borderRadius: "50%",
          background:
            "radial-gradient(circle at center, rgba(217,119,6,0.03) 0%, rgba(217,119,6,0.01) 35%, transparent 65%)",
          zIndex: 0,
          transition: "left 0.8s cubic-bezier(0.25, 0.1, 0.25, 1), top 0.8s cubic-bezier(0.25, 0.1, 0.25, 1)",
          left: -500,
          top: -500,
        }}
      />
      {/* Inner brighter core — smaller, faster follow */}
      <div
        ref={innerRef}
        className="pointer-events-none fixed"
        style={{
          width: 200,
          height: 200,
          borderRadius: "50%",
          background:
            "radial-gradient(circle at center, rgba(217,119,6,0.05) 0%, rgba(217,119,6,0.02) 40%, transparent 65%)",
          zIndex: 0,
          transition: "left 0.4s cubic-bezier(0.25, 0.1, 0.25, 1), top 0.4s cubic-bezier(0.25, 0.1, 0.25, 1)",
          left: -500,
          top: -500,
        }}
      />
    </>
  );
}
