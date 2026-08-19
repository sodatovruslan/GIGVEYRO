import styles from "./owner.module.css";

export function Heading({title,text}:{title:string;text:string}) {
  return <div className={styles.heading}><span>OWNER CONTROL CENTER</span><h1>{title}</h1><p>{text}</p></div>;
}
