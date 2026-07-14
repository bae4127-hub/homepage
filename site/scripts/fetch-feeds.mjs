// 블로그 RSS → data/posts.json, 유튜브 RSS → data/latest-video.json 자동 생성기
// GitHub Actions가 매일 실행 (.github/workflows/update-feeds.yml)
// 로컬 테스트: node scripts/fetch-feeds.mjs

import { writeFile, mkdir } from "node:fs/promises";

const RSS_URL = "https://rss.blog.naver.com/wormwood79.xml";
const YT_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UC7OCid3xzRUptzmHUvA7B4g";
const OUT_FILE = "data/posts.json";
const VIDEO_FILE = "data/latest-video.json";
const MAX_POSTS = 12;

// 메인에 노출하지 않을 카테고리 (블로그 개편 후 필요시 수정)
const HIDE_CATEGORIES = ["낙서장", "일상기록", "책읽기"];

function decodeEntities(s) {
  return s
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(n))
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/ /g, " ");
}

function pick(xml, tag) {
  const m = xml.match(new RegExp(`<${tag}>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?</${tag}>`));
  return m ? decodeEntities(m[1].trim()) : "";
}

const res = await fetch(RSS_URL, { headers: { "User-Agent": "Mozilla/5.0 (church-homepage-bot)" } });
if (!res.ok) throw new Error(`RSS 요청 실패: ${res.status}`);
const xml = await res.text();

const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].map(m => {
  const it = m[1];
  const d = new Date(pick(it, "pubDate"));
  return {
    title: pick(it, "title"),
    link: pick(it, "link").replace(/&amp;/g, "&").replace(/\?fromRss=true.*$/, ""),
    date: isNaN(d) ? "" : d.toISOString().slice(0, 10),
    category: pick(it, "category"),
  };
}).filter(p => p.title && !HIDE_CATEGORIES.includes(p.category));

// ===== 카드 썸네일 수집 =====
// 1순위: 네이버 대표 썸네일(사진 글) / 2순위: 글에 임베드된 유튜브 영상 썸네일 / 없으면 생략(대체 배경 표시)
const posts = items.slice(0, MAX_POSTS);
const naverHeaders = { "User-Agent": "Mozilla/5.0", "Referer": "https://m.blog.naver.com/wormwood79" };

const thumbMap = {};
try {
  const listRes = await fetch(
    "https://m.blog.naver.com/api/blogs/wormwood79/post-list?categoryNo=0&itemCount=30&page=1",
    { headers: naverHeaders }
  );
  if (listRes.ok) {
    const data = await listRes.json();
    for (const it of data.result?.items ?? []) {
      // 네이버 썸네일은 ?type=w800 크기 옵션이 없으면 404가 남
      if (it.hasThumbnail && it.thumbnailUrl) thumbMap[String(it.logNo)] = `${it.thumbnailUrl}?type=w800`;
    }
  }
} catch {}

for (const p of posts) {
  const logNo = (p.link.match(/\/(\d+)$/) || [])[1];
  if (!logNo) continue;
  if (thumbMap[logNo]) { p.image = thumbMap[logNo]; continue; }
  try {
    const html = await (await fetch(`https://m.blog.naver.com/wormwood79/${logNo}`, { headers: naverHeaders })).text();
    const m = html.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|watch\?v=|shorts\/))([\w-]{11})/);
    if (m) p.image = `https://i.ytimg.com/vi/${m[1]}/hqdefault.jpg`;
  } catch {}
}

await mkdir("data", { recursive: true });
await writeFile(OUT_FILE, JSON.stringify(posts, null, 2), "utf8");
console.log(`완료: ${OUT_FILE}에 ${posts.length}개 글 저장 (썸네일 ${posts.filter(p => p.image).length}개)`);

// ===== 유튜브 최신 설교 영상 =====
const ytRes = await fetch(YT_RSS_URL, { headers: { "User-Agent": "Mozilla/5.0 (church-homepage-bot)" } });
if (!ytRes.ok) throw new Error(`유튜브 RSS 요청 실패: ${ytRes.status}`);
const ytXml = await ytRes.text();

const videos = [...ytXml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].map(m => {
  const e = m[1];
  return {
    videoId: pick(e, "yt:videoId"),
    title: pick(e, "title"),
    date: pick(e, "published").slice(0, 10),
  };
}).filter(v => v.videoId);

// "[주일예배]"가 제목에 있는 가장 최근 영상 우선, 없으면 쇼츠가 아닌 최신 영상
const latest =
  videos.find(v => v.title.includes("주일예배")) ||
  videos.find(v => !v.title.includes("#shorts")) ||
  videos[0];

if (latest) {
  await writeFile(VIDEO_FILE, JSON.stringify(latest, null, 2), "utf8");
  console.log(`완료: ${VIDEO_FILE} ← ${latest.date} "${latest.title}"`);
}

// ===== 3. 공동체 성경읽기 (유튜브 재생목록 연동) =====
console.log("YouTube Playlist RSS 가져오기...");
const PLAYLIST_ID = "PLBXK2QPDTvS8";
if (PLAYLIST_ID !== "PLAYLIST_ID_HERE") {
  try {
    const plRes = await fetch(`https://www.youtube.com/feeds/videos.xml?playlist_id=${PLAYLIST_ID}`);
    if (plRes.ok) {
      const plXml = await plRes.text();
      const match = plXml.match(/<entry>([\s\S]*?)<\/entry>/);
      if (match) {
        const e = match[1];
        // 날짜는 영상 업로드일이 아니라 스크립트 실행(업데이트) 날짜로 설정
        const updateDate = new Date();
        const dateStr = new Date(updateDate.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10); // KST 변환
        
        const bibleData = {
          videoId: pick(e, "yt:videoId"),
          title: pick(e, "title"),
          date: dateStr,
        };
        await writeFile(new URL("../data/latest-bible.json", import.meta.url), JSON.stringify(bibleData, null, 2), "utf8");
        console.log(`완료: latest-bible.json ← ${bibleData.date} "${bibleData.title}"`);
      }
    }
  } catch (err) {
    console.error("Bible Playlist Error:", err);
  }
}
