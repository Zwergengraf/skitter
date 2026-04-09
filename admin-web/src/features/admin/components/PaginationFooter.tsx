import { Button } from "@/components/ui/button";

type PaginationFooterProps = {
  page: number;
  pageCount: number;
  pageSize: number;
  totalCount: number;
  onPrevious: () => void;
  onNext: () => void;
};

export function PaginationFooter({
  page,
  pageCount,
  pageSize,
  totalCount,
  onPrevious,
  onNext,
}: PaginationFooterProps) {
  const currentPage = Math.min(page, pageCount);
  const start = (currentPage - 1) * pageSize + 1;
  const end = Math.min(currentPage * pageSize, totalCount);

  return (
    <div className="flex items-center justify-between gap-3 border-t border-border pt-4 text-xs text-mutedForeground">
      <span>
        Showing {start}–{end} of {totalCount}
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={currentPage <= 1} onClick={onPrevious}>
          Previous
        </Button>
        <span>
          Page {currentPage} of {pageCount}
        </span>
        <Button size="sm" variant="outline" disabled={currentPage >= pageCount} onClick={onNext}>
          Next
        </Button>
      </div>
    </div>
  );
}
