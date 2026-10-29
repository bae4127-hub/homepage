// 블로그 RSS → data/posts.json, 유튜브 RSS → data/latest-video.json 자동 생성기
// GitHub Actions가 매일 실행 (.github/workflows/update.yml)
// 로컬 테스트: node scripts/fetch-feeds.mjs

import { writeFile, mkdir } from "node:fs/promises";

const RSS_URL = "https://rss.blog.naver.com/wormwood79.xml";
const YT_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UC7OCid3xzRUptzmHUvA7B4g";
const OUT_FILE = "data/posts.json";
const VIDEO_FILE = "data/latest-video.json";
const MAX_POSTS = 30;
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

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

async function fetchWithRetry(url, options = {}, maxRetries = 3, delayMs = 1500) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 12000);
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) return res;
      console.warn(`[시도 ${i + 1}/${maxRetries}] HTTP ${res.status}: ${url}`);
    } catch (err) {
      console.warn(`[시도 ${i + 1}/${maxRetries}] 요청 실패 (${err.message}): ${url}`);
    }
    if (i < maxRetries - 1) {
      await new Promise(r => setTimeout(r, delayMs * (i + 1)));
    }
  }
  return null;
}

async function updateFeeds() {
  await mkdir("data", { recursive: true });

  // 1. 네이버 블로그 RSS 수집
  console.log("네이버 블로그 RSS 수집 시작...");
  const res = await fetchWithRetry(RSS_URL, { headers: { "User-Agent": USER_AGENT } });
  if (res) {
    try {
      const xml = await res.text();
      const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].map(m => {
        const it = m[1];
        const title = pick(it, "title");
        let date = "";
        
        // 제목에서 'YY년 M월 D일' 또는 'YYYY년 M월 D일' 추출
        const dateMatch = title.match(/(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일/);
        if (dateMatch) {
          let year = dateMatch[1];
          year = year.length === 2 ? "20" + year : year;
          const month = dateMatch[2].padStart(2, '0');
          const day = dateMatch[3].padStart(2, '0');
          date = `${year}-${month}-${day}`;
        } else {
          const d = new Date(pick(it, "pubDate"));
          date = isNaN(d) ? "" : d.toISOString().slice(0, 10);
        }

        return {
          title: title,
          link: pick(it, "link").replace(/&amp;/g, "&").replace(/\?fromRss=true.*$/, ""),
          date: date,
          category: pick(it, "category"),
        };
      }).filter(p => p.title && !HIDE_CATEGORIES.includes(p.category));

      // 썸네일 수집
      const posts = items.slice(0, MAX_POSTS);
      const naverHeaders = { "User-Agent": USER_AGENT, "Referer": "https://m.blog.naver.com/wormwood79" };

      const thumbMap = {};
      try {
        const listRes = await fetchWithRetry(
          "https://m.blog.naver.com/api/blogs/wormwood79/post-list?categoryNo=0&itemCount=30&page=1",
          { headers: naverHeaders },
          2, 1000
        );
        if (listRes && listRes.ok) {
          const data = await listRes.json();
          for (const it of data.result?.items ?? []) {
            if (it.hasThumbnail && it.thumbnailUrl) thumbMap[String(it.logNo)] = `${it.thumbnailUrl}?type=w800`;
          }
        }
      } catch (err) {
        console.warn("썸네일 목록 수집 건너뜀:", err.message);
      }

      for (const p of posts) {
        const logNo = (p.link.match(/\/(\d+)$/) || [])[1];
        if (!logNo) continue;
        if (thumbMap[logNo]) { p.image = thumbMap[logNo]; continue; }
        try {
          const postRes = await fetchWithRetry(`https://m.blog.naver.com/wormwood79/${logNo}`, { headers: naverHeaders }, 1, 0);
          if (postRes && postRes.ok) {
            const html = await postRes.text();
            const m = html.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|watch\?v=|shorts\/))([\w-]{11})/);
            if (m) p.image = `https://i.ytimg.com/vi/${m[1]}/hqdefault.jpg`;
          }
        } catch {}
      }

      await writeFile(OUT_FILE, JSON.stringify(posts, null, 2), "utf8");
      console.log(`완료: ${OUT_FILE}에 ${posts.length}개 글 저장 (썸네일 ${posts.filter(p => p.image).length}개)`);
    } catch (parseErr) {
      console.error("블로그 RSS 파싱 오류:", parseErr.message);
    }
  } else {
    console.warn("블로그 RSS 수집 실패 — 기존 posts.json을 보존합니다.");
  }

  // 2. 유튜브 최신 주일설교 수집 (간헐적 500에 안전하게 대응)
  console.log("유튜브 RSS 수집 시작...");
  try {
    const ytRes = await fetchWithRetry(YT_RSS_URL, { headers: { "User-Agent": USER_AGENT } }, 3, 2000);
    if (ytRes && ytRes.ok) {
      const ytXml = await ytRes.text();
      const videos = [...ytXml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].map(m => {
        const e = m[1];
        return {
          videoId: pick(e, "yt:videoId"),
          title: pick(e, "title"),
          date: (pick(e, "published") || "").slice(0, 10),
        };
      }).filter(v => v.videoId);

      const latest =
        videos.find(v => v.title.includes("주일예배")) ||
        videos.find(v => !v.title.includes("#shorts")) ||
        videos[0];

      if (latest) {
        await writeFile(VIDEO_FILE, JSON.stringify(latest, null, 2), "utf8");
        console.log(`완료: ${VIDEO_FILE} ← ${latest.date} "${latest.title}"`);
      }
    } else {
      console.warn("유튜브 RSS 응답 없음 (간헐적 500 등) — 기존 latest-video.json을 보존합니다.");
    }
  } catch (ytErr) {
    console.warn("유튜브 영상 수집 중 예외 발생 (기존 latest-video.json 보존):", ytErr.message);
  }
}

updateFeeds();
