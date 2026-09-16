'use client';
import Image from 'next/image';
import {useState} from 'react';
import type {EVSignal} from '@/lib/types';
import styles from './ResearchViews.module.css';

export default function PlayerPortrait({signal}:{signal:EVSignal}) {
  const url=signal.availability?.player_image_url;
  const [failed,setFailed]=useState<string>();
  return <span className={styles.playerPortrait} aria-hidden="true">
    {url && failed!==url ? <Image src={url} alt="" width={64} height={64} unoptimized referrerPolicy="no-referrer" onError={()=>setFailed(url)} />
      : signal.player.split(/\s+/).map(word=>word[0]).slice(0,2).join('')}
  </span>;
}
