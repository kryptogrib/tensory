"use client";

import { useRef, useCallback, useEffect } from "react";

export function CursorGlow() {
  const glowRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const posRef = useRef({ x: 0, y: 0 });

  const updatePosition = useCallback(() => {
    if (glowRef.current) {
      glowRef.current.style.transform = `translate(${posRef.current.x}px, ${posRef.current.y}px)`;
    }
    rafRef.current = null;
  }, []);

  const handlePointerMove = useCallback(
    (e: PointerEvent) => {
      posRef.current = { x: e.clientX - 100, y: e.clientY - 100 };
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(updatePosition);
      }
    },
    [updatePosition]
  );

  useEffect(() => {
    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [handlePointerMove]);

  return (
    <div
      ref={glowRef}
      className="pointer-events-none fixed left-0 top-0 z-0"
      style={{
        width: 200,
        height: 200,
        borderRadius: "50%",
        background: "radial-gradient(circle 100px, rgba(217,119,6,0.04), transparent)",
        willChange: "transform",
      }}
    />
  );
}
