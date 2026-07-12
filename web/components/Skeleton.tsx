"use client";

import type { ReactNode } from "react";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className = "" }: SkeletonProps) {
  return <div className={`animate-pulse bg-muted rounded ${className}`} />;
}

export function SkeletonText({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-3 ${i === lines - 1 ? "w-2/3" : "w-full"}`}
        />
      ))}
    </div>
  );
}

export function SkeletonMessage() {
  return (
    <div className="space-y-2 p-3">
      <Skeleton className="h-3 w-1/4" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-5/6" />
      <Skeleton className="h-3 w-3/4" />
    </div>
  );
}

export function SidebarSkeleton() {
  return (
    <aside className="w-64 border-r border-border bg-muted/30 flex flex-col">
      <div className="p-3 border-b border-border space-y-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-6 w-full" />
      </div>
      <div className="flex-1 p-2 space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
      <div className="p-2 border-t border-border space-y-2">
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    </aside>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-8">
      {icon && <div className="text-4xl mb-3 text-muted-foreground">{icon}</div>}
      <div className="text-base font-medium mb-1">{title}</div>
      {description && (
        <div className="text-sm text-muted-foreground max-w-sm">{description}</div>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

