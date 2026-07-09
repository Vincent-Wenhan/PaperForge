export default function Loading() {
  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <div className="w-64 border-r border-border bg-muted/30 animate-pulse" />
      <div className="flex-1 flex flex-col gap-3 p-4">
        <div className="h-6 w-48 bg-muted animate-pulse rounded" />
        <div className="h-4 w-32 bg-muted animate-pulse rounded" />
        <div className="flex-1 space-y-2 mt-4">
          <div className="h-4 bg-muted animate-pulse rounded" />
          <div className="h-4 w-3/4 bg-muted animate-pulse rounded" />
          <div className="h-4 w-1/2 bg-muted animate-pulse rounded" />
        </div>
      </div>
    </div>
  );
}
