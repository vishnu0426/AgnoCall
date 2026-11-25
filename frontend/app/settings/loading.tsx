import PageContainer from "@/components/PageContainer";
import { Skeleton } from "@/components/Skeleton";

// Shown the instant the link is clicked, while the page's data loads.
export default function Loading() {
  return (
    <PageContainer>
      <Skeleton className="h-6 w-32 mb-2" />
      <Skeleton className="h-4 w-64 mb-7" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-lg" />
    </PageContainer>
  );
}
