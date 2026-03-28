"use client";

interface HudWindowProps {
  title?: string;
  action?: { label: string; onClick: () => void };
  className?: string;
  children: React.ReactNode;
}

export function HudWindow({ title, action, className, children }: HudWindowProps) {
  return (
    <div
      className={`rounded-lg ${className ?? ""}`}
      style={{
        background: "rgba(10, 9, 8, 0.82)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid rgba(217, 119, 6, 0.06)",
      }}
    >
      {title && (
        <div className="flex items-center justify-between px-3 py-2">
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ background: "#d97706" }}
            />
            <span
              className="text-[0.6rem] font-bold uppercase tracking-wider"
              style={{ color: "#8a7e72" }}
            >
              {title}
            </span>
          </div>
          {action && (
            <button
              onClick={action.onClick}
              className="cursor-pointer text-[0.6rem] uppercase tracking-wider transition-colors hover:brightness-125"
              style={{ color: "#d97706" }}
            >
              {action.label}
            </button>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
