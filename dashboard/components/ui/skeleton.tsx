import type * as React from "react";
import { cn } from "@/lib/utils";

// shadcn/ui Skeleton (new-york). Para loading states en bandeja (PR1 commit 2).
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
