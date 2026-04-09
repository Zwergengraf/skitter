import type { ReactNode } from "react";

import { TableCell, TableRow } from "@/components/ui/table";

type TableMessageRowProps = {
  colSpan: number;
  children: ReactNode;
};

export function TableMessageRow({ colSpan, children }: TableMessageRowProps) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="text-center text-sm text-mutedForeground">
        {children}
      </TableCell>
    </TableRow>
  );
}
