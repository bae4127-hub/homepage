// RSS 장애 시 공개 채널의 선택된 동영상/라이브 탭만 사용합니다.
export const CHANNEL_ID = "UC7OCid3xzRUptzmHUvA7B4g";

function text(value) {
  return value?.simpleText ?? value?.content ?? value?.runs?.map(r => r.text).join("") ?? "";
}

function dateInTitle(title) {
  const match = title.match(/(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일/);
  if (!match) return "";
  const date = `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
  const parsed = new Date(`${date}T00:00:00Z`);
  return !isNaN(parsed) && parsed.toISOString().slice(0, 10) === date ? date : "";
}

export function selectLatestSermon(videos, previous = null, now = new Date()) {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  const candidates = videos.filter(v =>
    /^[\w-]{11}$/.test(v.videoId ?? "") && /주일\s*예배/.test(v.title ?? "") &&
    !/테스트|#?shorts|쇼츠/i.test(v.title) && !v.unavailable &&
    /^\d{4}-\d{2}-\d{2}$/.test(v.date ?? "") && v.date <= today
  ).sort((a, b) => b.date.localeCompare(a.date));
  const latest = candidates[0];
  if (!latest || (previous?.date && latest.date < previous.date)) return null;
  return { videoId: latest.videoId, title: latest.title, date: latest.date };
}

export function parseChannelPage(html) {
  const marker = /(?:var\s+ytInitialData\s*=|window\["ytInitialData"\]\s*=)\s*/.exec(html);
  if (!marker) throw new Error("유튜브 채널 데이터가 없습니다");
  // JSON만 읽고 페이지의 스크립트는 실행하지 않습니다.
  const json = html.slice(marker.index + marker[0].length).split("</script>")[0].trim().replace(/;\s*$/, "");
  const data = JSON.parse(json);
  if (data.metadata?.channelMetadataRenderer?.externalId !== CHANNEL_ID) {
    throw new Error("유튜브 채널 ID가 일치하지 않습니다");
  }
  const tabs = data.contents?.twoColumnBrowseResultsRenderer?.tabs ?? [];
  const selected = tabs.find(t => t.tabRenderer?.selected)?.tabRenderer;
  if (!selected?.content) throw new Error("선택된 유튜브 채널 탭이 없습니다");
  const videos = [];
  function walk(node) {
    if (!node || typeof node !== "object") return;
    if (node.videoRenderer) {
      const v = node.videoRenderer;
      const title = text(v.title);
      const status = JSON.stringify([v.badges, v.thumbnailOverlays]);
      videos.push({ videoId: v.videoId, title, date: dateInTitle(title),
        unavailable: !!v.upcomingEventData || /LIVE_NOW|"style":"LIVE"|UPCOMING/.test(status) });
      return;
    }
    if (node.lockupViewModel) {
      const v = node.lockupViewModel;
      if (v.contentType !== "LOCKUP_CONTENT_TYPE_VIDEO") return;
      const title = text(v.metadata?.lockupMetadataViewModel?.title);
      const status = JSON.stringify(v.contentImage?.thumbnailViewModel?.overlays ?? []);
      videos.push({ videoId: v.contentId, title, date: dateInTitle(title),
        unavailable: /LIVE_NOW|BADGE_STYLE_LIVE|UPCOMING|예정|예약|스트리밍 중|Live now/i.test(status) });
      return;
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(walk);
      else if (value && typeof value === "object") walk(value);
    }
  }
  walk(selected.content);
  return videos;
}

export function parseYouTubeRss(xml) {
  const tag = (entry, name) => {
    const value = entry.match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`))?.[1] ?? "";
    return value.replace(/^<!\[CDATA\[([\s\S]*)\]\]>$/, "$1").trim()
      .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&apos;/g, "'");
  };
  return [...xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].map(([, entry]) => {
    const title = tag(entry, "title");
    return { videoId: tag(entry, "yt:videoId"), title,
      date: dateInTitle(title) || tag(entry, "published").slice(0, 10) };
  });
}

export async function findLatestSermon(fetchText, previous = null) {
  try {
    const xml = await fetchText(`https://www.youtube.com/feeds/videos.xml?channel_id=${CHANNEL_ID}`);
    const latest = xml && selectLatestSermon(parseYouTubeRss(xml), previous);
    if (latest) return { latest, source: "RSS" };
  } catch (error) {
    console.warn("유튜브 RSS 해석 실패:", error.message);
  }
  const results = await Promise.allSettled(["streams", "videos"].map(async tab => {
    const html = await fetchText(`https://www.youtube.com/channel/${CHANNEL_ID}/${tab}?hl=ko`);
    if (!html) throw new Error(`${tab} 페이지 요청 실패`);
    return parseChannelPage(html);
  }));
  for (const result of results) {
    if (result.status === "rejected") console.warn("유튜브 대체 수집:", result.reason.message);
  }
  const candidates = results.flatMap(r => r.status === "fulfilled" ? r.value : []);
  const latest = selectLatestSermon(candidates, previous);
  return { latest, source: "채널 페이지" };
}
