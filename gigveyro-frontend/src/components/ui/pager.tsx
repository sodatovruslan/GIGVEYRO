"use client";

import { useTranslations } from "next-intl";

import styles from "./pager.module.css";

interface PagerProps {
  offset: number;
  limit: number;
  itemCount: number;
  total?: number;
  onPage: (offset: number) => void;
}

export function Pager({ offset, limit, itemCount, total, onPage }: PagerProps) {
  const common = useTranslations("common");
  const hasPrev = offset > 0;
  const hasNext = total !== undefined ? offset + limit < total : itemCount === limit;
  if (!hasPrev && !hasNext) return null;
  return (
    <div className={styles.pager}>
      <span>
        {total !== undefined
          ? common("fromTotal", { from: total === 0 ? 0 : offset + 1, to: Math.min(offset + limit, total), total })
          : common("pageOf", { page: Math.floor(offset / limit) + 1 })}
      </span>
      <button type="button" disabled={!hasPrev} onClick={() => onPage(Math.max(0, offset - limit))}>{common("back")}</button>
      <button type="button" disabled={!hasNext} onClick={() => onPage(offset + limit)}>{common("next")}</button>
    </div>
  );
}
