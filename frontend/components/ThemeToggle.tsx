'use client';

import {Moon,Sun} from 'lucide-react';
import {useEffect,useState} from 'react';
import styles from './ThemeToggle.module.css';

type Theme='light'|'dark';

function preferredTheme():Theme {
  const saved=window.localStorage.getItem('linework-theme');
  return saved==='light' || saved==='dark' ? saved
    : window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function ThemeToggle() {
  const [theme,setTheme]=useState<Theme|null>(null);
  useEffect(()=>{
    const frame=window.requestAnimationFrame(()=>{
      const initial=preferredTheme();
      document.documentElement.dataset.theme=initial;
      setTheme(initial);
    });
    return()=>window.cancelAnimationFrame(frame);
  },[]);
  const next=theme==='dark' ? 'light' : 'dark';
  return <button type="button" className={styles.toggle} aria-label={`Use ${next} mode`}
    title={`Use ${next} mode`} onClick={()=>{
      document.documentElement.dataset.theme=next;
      window.localStorage.setItem('linework-theme',next);
      setTheme(next);
    }}>
    {theme==='dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
  </button>;
}
