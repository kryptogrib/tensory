export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-8">
      <div className="flex flex-col items-center gap-2">
        <h1 className="text-2xl font-bold text-ember-accent">
          TENSORY
        </h1>
        <p className="text-sm text-ember-text-secondary">
          Context-aware memory for AI agents
        </p>
      </div>
      <div className="w-64 border-t border-ember-accent/20" />
      <p className="text-xs text-ember-text-tertiary">
        Dashboard loading...
      </p>
    </div>
  );
}
