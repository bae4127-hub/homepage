import test from "node:test";
import assert from "node:assert/strict";
import { CHANNEL_ID, parseChannelPage, parseYouTubeRss, selectLatestSermon, findLatestSermon } from "./youtube-feed.mjs";

const now = new Date("2026-10-30T05:00:00Z");
const sermon = (videoId, date) => ({ videoId, title: `[주일예배] ${date.replace(/(\d+)-(\d+)-(\d+)/, "$1년 $2월 $3일")} 설교`, date });
const latest = sermon("rqNte0d9l7g", "2026-10-25");
function page(videos, channel = CHANNEL_ID) {
  const data = { metadata: { channelMetadataRenderer: { externalId: channel } }, contents: {
    twoColumnBrowseResultsRenderer: { tabs: [{ tabRenderer: { selected: true, content: {
      richGridRenderer: { contents: videos.map(v => ({ lockupViewModel: {
        contentId: v.videoId, contentType: "LOCKUP_CONTENT_TYPE_VIDEO",
        metadata: { lockupMetadataViewModel: { title: { content: v.title } } },
        contentImage: { thumbnailViewModel: { overlays: v.overlays ?? [] } }
      } })) }
    } } }] }
  } };
  return `<script>var ytInitialData = ${JSON.stringify(data)};</script>`;
}

test("RSS entries decode CDATA and prefer sermon date over delayed upload date", () => {
  const xml = `<feed><entry><yt:videoId>${latest.videoId}</yt:videoId><title><![CDATA[${latest.title} &amp; 은혜]]></title><published>2026-10-29T00:00:00Z</published></entry></feed>`;
  const [video] = parseYouTubeRss(xml);
  assert.equal(video.date, "2026-10-25");
  assert.match(video.title, /& 은혜$/);
  assert.equal(selectLatestSermon([video], null, now).videoId, latest.videoId);
});

test("channel fallback reads new layout and rejects another channel", () => {
  assert.deepEqual(selectLatestSermon(parseChannelPage(page([latest])), null, now), latest);
  assert.throws(() => parseChannelPage(page([latest], "another-channel")), /채널 ID/);
  assert.throws(() => parseChannelPage("<html>consent</html>"), /데이터/);
});

test("selection excludes tests, shorts, future and active broadcasts; never rolls back", () => {
  const older = sermon("IMr4fHqZxXc", "2026-10-04");
  const future = sermon("aaaaaaaaaaa", "2026-11-01");
  const testing = { ...latest, title: latest.title + " 테스트" };
  const short = { ...latest, title: latest.title + " #Shorts" };
  const active = { ...latest, overlays: [{ badgeStyle: "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE" }] };
  const videos = parseChannelPage(page([testing, short, active, future, older, latest]));
  assert.deepEqual(selectLatestSermon(videos, null, now), latest);
  assert.equal(selectLatestSermon([older], latest, now), null);
});

test("legacy layout only reads selected channel tab", () => {
  const data = { metadata: { channelMetadataRenderer: { externalId: CHANNEL_ID } }, contents: {
    twoColumnBrowseResultsRenderer: { tabs: [{ tabRenderer: { selected: true, content: {
      videoRenderer: { videoId: latest.videoId, title: { runs: [{ text: latest.title }] } }
    } } }, { tabRenderer: { content: { videoRenderer: { videoId: "aaaaaaaaaaa", title: { simpleText: "추천 영상" } } } } }] }
  } };
  assert.deepEqual(selectLatestSermon(parseChannelPage(`<script>var ytInitialData = ${JSON.stringify(data)};</script>`), null, now), latest);
});

test("HTTP failure falls back to channel; total failure produces no replacement", async () => {
  const calls = [];
  const result = await findLatestSermon(async url => {
    calls.push(url);
    return url.includes("feeds/") ? null : page([latest]);
  });
  assert.deepEqual(result.latest, latest);
  assert.equal(result.source, "채널 페이지");
  assert.equal(calls.length, 3);
  assert.equal((await findLatestSermon(async () => null, latest)).latest, null);
});
