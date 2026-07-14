// 교회 소식 섹션: data/posts.json을 읽어 최신 블로그 글 카드를 표시.
// posts.json은 GitHub Actions가 매일 블로그 RSS에서 자동 생성 (scripts/fetch-feeds.mjs).
// 로컬에서 미리보기할 때는 폴더에 들어있는 샘플 데이터가 표시됩니다.

const POSTS_URL = "data/posts.json";
const MAX_POSTS = 6;

// file:// 로 직접 열었을 때(보안 정책으로 fetch 차단) 대신 표시할 예비 목록 (실제 글)
const FALLBACK_POSTS = [
  { title: "진짜를 만나면, 가짜에 목마르지 않습니다", link: "https://blog.naver.com/wormwood79/224212885019", date: "2026-03-12", category: "말씀쇼츠", image: "https://i.ytimg.com/vi/KHaOw9tYbvQ/hqdefault.jpg" },
  { title: "믿음은 악력이 아니라 '빈손'입니다", link: "https://blog.naver.com/wormwood79/224212904727", date: "2026-03-12", category: "말씀쇼츠", image: "https://i.ytimg.com/vi/lT_xdrQUkK8/hqdefault.jpg" },
  { title: "내 안의 말씀이 죽어간다 — 좋은 밭의 비밀", link: "https://blog.naver.com/wormwood79/224201373185", date: "2026-03-02", category: "말씀쇼츠", image: "https://i.ytimg.com/vi/TxrIC4r6Mi0/hqdefault.jpg" },
  { title: "바닥이 편하다고 느낀다면, 그게 정말 나다운 걸까?", link: "https://blog.naver.com/wormwood79/224183503554", date: "2026-02-14", category: "말씀쇼츠", image: "https://i.ytimg.com/vi/kg7LKQ-rros/hqdefault.jpg" }
];

function renderPosts(posts) {
  const wrap = document.getElementById("blog-posts");
  // 이미지가 안 불러와지면 onerror로 제거 → 뒤에 깔린 대체 배경(⛪ 그라데이션)이 보임
  wrap.innerHTML = posts.slice(0, MAX_POSTS).map(p => `
    <a class="post-card" href="${p.link}" target="_blank" rel="noopener">
      <div class="post-thumb">
        ${p.image ? `<img src="${p.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
      </div>
      <div class="post-body">
        <span class="post-cat">${p.category || "소식"}</span>
        <h3>${p.title}</h3>
        <time>${p.date}</time>
      </div>
    </a>
  `).join("");
  markReveal(wrap.querySelectorAll(".post-card")); // 새로 생긴 카드에도 등장 애니메이션
}

async function loadPosts() {
  let posts;
  try {
    const res = await fetch(POSTS_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    posts = await res.json();
  } catch (e) {
    posts = FALLBACK_POSTS; // 로컬 미리보기 등 fetch 불가 환경
  }
  renderPosts(posts);
  renderFamilyWorship(posts);
}

// ===== 가정예배 · 밤기도회 코너 =====
// 블로그 글 제목에 "오렌지카드" / "선포기도"가 들어 있으면 최신 글이 자동으로 여기 표시됨.
// (블로그 템플릿 09·10번의 제목 규칙을 지키면 됨 — 별도 관리 불필요)
function renderFamilyWorship(posts) {
  const corners = [
    { id: "fw-orange", match: "오렌지카드", badge: "🍊 오렌지카드", label: "가정예배 순서지",
      guide: "블로그에 [오렌지카드] 제목으로 글을 올리면 이 자리에 자동으로 표시됩니다." },
    { id: "fw-prayer", match: "선포기도", badge: "🌙 선포기도문", label: "밤기도회",
      guide: "블로그에 [선포기도문] 제목으로 글을 올리면 이 자리에 자동으로 표시됩니다." }
  ];
  corners.forEach(c => {
    const el = document.getElementById(c.id);
    const post = posts.find(p => p.title.includes(c.match));
    if (post) {
      el.innerHTML = `
        <span class="fw-badge">${c.badge}</span>
        <span class="fw-label">${c.label}</span>
        <h3><a href="${post.link}" target="_blank" rel="noopener">${post.title}</a></h3>
        <time>${post.date}</time>
        <a class="fw-cta" href="${post.link}" target="_blank" rel="noopener">이번 주 내용 보기 →</a>`;
    } else {
      el.innerHTML = `
        <span class="fw-badge">${c.badge}</span>
        <span class="fw-label">${c.label}</span>
        <p class="fw-empty">${c.guide}</p>`;
    }
  });
  markReveal(document.querySelectorAll(".fw-card"));
}

async function loadBible() {
  const el = document.getElementById("fw-bible");
  if (!el) return;
  try {
    const res = await fetch("data/latest-bible.json", { cache: "no-store" });
    if (!res.ok) throw new Error("no bible data");
    const data = await res.json();
    el.innerHTML = `
      <span class="fw-badge">📖 공동체성경읽기</span>
      <span class="fw-label">공동체 성경읽기</span>
      <h3><a href="https://youtu.be/${data.videoId}" target="_blank" rel="noopener">${data.title}</a></h3>
      <time>${data.date}</time>
      <a class="fw-cta" href="https://youtu.be/${data.videoId}" target="_blank" rel="noopener">오늘 말씀 듣기 →</a>`;
  } catch (e) {
    el.innerHTML = `
      <span class="fw-badge">📖 공동체성경읽기</span>
      <span class="fw-label">공동체 성경읽기</span>
      <p class="fw-empty">오늘의 성경읽기 말씀이 아직 업데이트되지 않았습니다.</p>`;
  }
}
loadBible();

loadPosts();

// 이번 주 말씀: data/latest-video.json의 최신 설교로 영상 교체.
// (GitHub Actions가 매일 유튜브 RSS에서 자동 생성. 읽기 실패 시 index.html의 기본 영상 유지)
async function loadLatestVideo() {
  try {
    const res = await fetch("data/latest-video.json", { cache: "no-store" });
    if (!res.ok) return;
    const v = await res.json();
    if (v.videoId) {
      const link = document.getElementById("sermon-link");
      const thumb = document.getElementById("sermon-thumb");
      if (link && thumb) {
        link.href = `https://www.youtube.com/watch?v=${v.videoId}`;
        thumb.src = `https://i.ytimg.com/vi/${v.videoId}/maxresdefault.jpg`;
        if (v.title) thumb.alt = v.title;
      }
    }
  } catch (e) { /* 기본 영상 유지 */ }
}

loadLatestVideo();

// ===== 이웃사랑 (고정 목록) =====
// data/outreach.json에 적힌 글을 그대로 표시. 새 나눔 이야기가 생기면 그 파일에 항목 추가.
const OUTREACH_FALLBACK = [
  { title: "성탄헌금으로 함께한 이웃사랑: 목회자 장애자녀가정 지원 동참", description: "성탄헌금을 모아 밀알복지재단을 통해 장애 자녀를 양육하는 목회자 다섯 가정에 생계비를 전했습니다. 성탄의 기쁨이 예배당 밖 누군가의 삶에 닿기를 바라는 마음이었습니다.", link: "https://blog.naver.com/wormwood79/224174179962", date: "2026-02-06", image: "https://mblogthumb-phinf.pstatic.net/MjAyNjAyMDZfMTYy/MDAxNzcwMzY0MDIwMzY1.JZj6n8Utelzn24VUmC8h6njE-Y-WgWH9iZeIP-_aLFQg.EpffgY9hiQBVtQVXLszRGzwkbafa324c4_UnatVRPzIg.PNG/KakaoTalk_20260206_164612807.png?type=w800" },
  { title: "청라강성교회 굿윌스토어 물품기증 캠페인 결과 보고", description: "성도들이 모은 물품 143점을 굿윌스토어에 기증해 장애인의 일자리와 자립을 응원했습니다. 온실가스 300kg을 줄여 소나무 46그루를 심은 효과도 함께였습니다.", link: "https://blog.naver.com/wormwood79/223859162903", date: "2025-05-08", image: "https://mblogthumb-phinf.pstatic.net/MjAyNTA1MDhfMiAg/MDAxNzQ2Njg5NjY0MDg1.pRACBmUPqmn6dmX22IbRjRml4Qvvgw0PWn0yoDp60KYg.dt6gJlTxCpEtTPkQQZ-2TLFlREuf3jEDLDDbXpsVli8g.PNG/%B9%B0%C7%B0%B1%E2%C1%F5%B0%E1%B0%FA.png?type=w800" }
];

function renderOutreach(items) {
  const wrap = document.getElementById("outreach-list");
  wrap.innerHTML = items.map(p => `
    <a class="outreach-card" href="${p.link}" target="_blank" rel="noopener">
      ${p.image ? `<div class="outreach-thumb"><img src="${p.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.remove()"></div>` : ""}
      <div class="outreach-body">
        <h3>${p.title}</h3>
        ${p.description ? `<p>${p.description}</p>` : ""}
        <time>${p.date}</time>
      </div>
    </a>
  `).join("");
  markReveal(wrap.querySelectorAll(".outreach-card"));
}

async function loadOutreach() {
  try {
    const res = await fetch("data/outreach.json", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    renderOutreach(await res.json());
  } catch (e) {
    renderOutreach(OUTREACH_FALLBACK);
  }
}

loadOutreach();

// ===== 고정 배너 및 모달 (여러 개 가능) =====
// data/notice.json의 목록에서 표시 조건(active + 기간)에 맞는 항목을 표시.
// isModal: true 인 항목은 모달 팝업으로, 나머지는 인페이지 배너로 노출.
async function loadNotice() {
  try {
    const res = await fetch("data/notice.json", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    const list = Array.isArray(data) ? data : [data];

    const today = new Date().toISOString().slice(0, 10);
    const visible = list.filter(n =>
      n.active &&
      (!n.start || today >= n.start) &&
      (!n.end || today <= n.end)
    );
    if (visible.length === 0) return;

    // 배너와 모달 분리
    const modals = visible.filter(n => n.isModal);
    const banners = visible.filter(n => !n.isModal);

    // 1. 일반 배너 렌더링
    if (banners.length > 0) {
      const wrap = document.getElementById("notice-list");
      wrap.innerHTML = banners.map(n => `
        <a class="notice-banner" href="${n.link || "#"}" target="_blank" rel="noopener">
          ${n.image ? `<div class="notice-thumb"><img src="${n.image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.remove()"></div>` : ""}
          <div class="notice-body">
            ${n.badge ? `<span class="notice-badge">${n.badge}</span>` : ""}
            <h3>${n.title}</h3>
            ${n.description ? `<p>${n.description}</p>` : ""}
            <span class="notice-cta">${n.linkText || "자세히 보기"} →</span>
          </div>
        </a>
      `).join("");
      wrap.classList.toggle("notice-multi", banners.length > 1);
      document.getElementById("notice").hidden = false;
    }

    // 2. 모달 팝업 렌더링 (가장 앞의 1개만)
    if (modals.length > 0) {
      const modalData = modals[0];
      const hideKey = `hideModal_${modalData.title}`;
      const hideUntil = localStorage.getItem(hideKey);
      
      if (!hideUntil || Date.now() > parseInt(hideUntil, 10)) {
        renderModal(modalData, hideKey);
      }
    }
  } catch (e) { /* 에러 시 배너 없이 진행 */ }
}

function renderModal(data, hideKey) {
  const root = document.getElementById("modal-root");
  if (!root) return;
  root.innerHTML = `
    <div class="modal-overlay" id="site-modal">
      <div class="modal-dialog">
        <div class="modal-header">
          <button class="modal-close" id="modal-close-btn">&times;</button>
          ${data.image ? `<img src="${data.image}" alt="" class="modal-thumb" referrerpolicy="no-referrer">` : ""}
        </div>
        <div class="modal-body">
          <h3>${data.title}</h3>
          ${data.description ? `<p>${data.description}</p>` : ""}
          <a href="${data.link || "#"}" target="_blank" rel="noopener" class="btn-primary" id="modal-cta-btn">${data.linkText || "자세히 보기"}</a>
        </div>
        <div class="modal-footer">
          <label><input type="checkbox" id="modal-hide-chk"> 7일간 보지 않기</label>
          <button id="modal-close-txt">닫기</button>
        </div>
      </div>
    </div>
  `;
  
  const modal = document.getElementById("site-modal");
  // 강제 리플로우 후 클래스 추가로 애니메이션 동작
  modal.offsetHeight; 
  modal.classList.add("show");

  const closeModal = () => {
    if (document.getElementById("modal-hide-chk").checked) {
      localStorage.setItem(hideKey, Date.now() + 7 * 24 * 60 * 60 * 1000);
    }
    modal.classList.remove("show");
    setTimeout(() => { root.innerHTML = ""; }, 300);
  };

  document.getElementById("modal-close-btn").onclick = closeModal;
  document.getElementById("modal-close-txt").onclick = closeModal;
  document.getElementById("modal-cta-btn").onclick = closeModal;
}

loadNotice();

// ===== 스크롤 등장 애니메이션 =====
// 화면에 들어오는 요소에 .visible을 붙여 부드럽게 떠오르게 함 (style.css의 .reveal 참고)
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const revealObserver = new IntersectionObserver(entries => {
  entries.forEach(en => {
    if (en.isIntersecting) {
      en.target.classList.add("visible");
      revealObserver.unobserve(en.target);
    }
  });
}, { threshold: 0.12 });

function markReveal(elements) {
  if (reduceMotion) return; // 모션 최소화 설정 시 애니메이션 생략
  elements.forEach((el, i) => {
    el.classList.add("reveal");
    el.style.transitionDelay = `${Math.min(i * 70, 350)}ms`; // 카드가 차례로 등장
    revealObserver.observe(el);
  });
}

markReveal(document.querySelectorAll(
  ".section h2, .section-desc, .video-wrap, .welcome-card, .address, .map-wrap, .transit, .more-link, .vision-logo-card, .value-card"
));
