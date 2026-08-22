"use client";

import { useTranslations } from "next-intl";

import styles from "./owner.module.css";

export function Heading({title,text}:{title:string;text:string}) {
  const t = useTranslations("analytics");
  return <div className={styles.heading}><span>{t("eyebrow")}</span><h1>{title}</h1><p>{text}</p></div>;
}
