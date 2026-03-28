"use client";

/* ─── Cursor Glow ────────────────────────────────────────────────────
 *
 * Ambient light that follows the cursor with smooth interpolation.
 * Uses lerp (linear interpolation) for a floaty, delayed follow
 * instead of snapping directly to cursor position.
 *
 * Two layers: a large soft outer glow + a smaller brighter inner.
 * ──────────────────────────────────────────────────────────────────── */

import { useRef, useEffect } from "react";

export function CursorGlow() {
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const mouseRef = useRef({ x: -500, y: -500 }); // start offscreen
  const currentRef = useRef({ x: -500, y: -500 });
  const animatingRef = useRef(false);

  useEffect(() => {
    function onPointerMove(e: PointerEvent) {
      mouseRef.current = { x: e.clientX, y: e.clientY };

      if (!animatingRef.current) {
        animatingRef.current = true;
        requestAnimationFrame(animate);
      }
    }

    function animate() {
      const mouse = mouseRef.current;
      const current = currentRef.current;

      // Lerp factor: 0.08 = slow/floaty follow, 0.15 = medium
      const lerpFactor = 0.07;
      current.x += (mouse.x - current.x) * lerpFactor;
      current.y += (mouse.y - current.y) * lerpFactor;

      if (outerRef.current) {
        outerRef.current.style.transform =
          `translate(${current.x - 200}px, ${current.y - 200}px)`;
      }
      if (innerRef.current) {
        // Inner follows slightly faster for a parallax feel
        const innerX = current.x + (mouse.x - current.x) * 0.15;
        const innerY = current.y + (mouse.y - current.y) * 0.15;
        innerRef.current.style.transform =
          `translate(${innerX - 80}px, ${innerY - 80}px)`;
      }

      // Keep animating if cursor moved recently
      const dx = mouse.x - current.x;
      const dy = mouse.y - current.y;
      if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
        requestAnimationFrame(animate);
      } else {
        animatingRef.current = false;
      }
    }

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    return () => window.removeEventListener("pointermove", onPointerMove);
  }, []);

  return (
    <>
      {/* Outer soft glow — large, very subtle */}
      <div
        ref={outerRef}
        className="pointer-events-none fixed left-0 top-0"
        style={{
          width: 400,
          height: 400,
          borderRadius: "50%",
          background:
            "radial-gradient(circle at center, rgba(217,119,6,0.025) 0%, rgba(217,119,6,0.01) 40%, transparent 70%)",
          willChange: "transform",
          zIndex: 0,
          filter: "blur(30px)",
        }}
      />
      {/* Inner brighter core — smaller, slightly faster */}
      <div
        ref={innerRef}
        className="pointer-events-none fixed left-0 top-0"
        style={{
          width: 160,
          height: 160,
          borderRadius: "50%",
          background:
            "radial-gradient(circle at center, rgba(217,119,6,0.04) 0%, transparent 60%)",
          willChange: "transform",
          zIndex: 0,
        }}
      />
    </>
  );
}
