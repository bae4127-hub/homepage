# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

청라강성교회(인천 청라, 담임 권영호 목사) 홈페이지 프로젝트. 사용자는 비개발자(목회자)이므로 **한국어로 소통**하고, 기술 용어는 풀어서 설명할 것. 모든 콘텐츠의 `[대괄호]` 부분은 사용자가 나중에 채우는 자리표시자다.

## 교회 기본 정보 (사용자·주보에서 확인됨 — 재조사 불필요)

- 주소: **인천광역시 서구 청라한내로162번길 4-6, 4층 (우 22752)** / 전화: **010-8011-7905**
- 예배: 주일예배 **주일 오전 11시**, **매일 선포기도회 밤 9시**. 새벽기도는 따로 없고 가정에서 공동체 성경읽기(큐티)로 대체. 교회학교·수요예배 없음(주보 기준)
- 교단: 대한예수교장로회(**합신**) / 표어: "바른신학 바른교회 바른생활" / 비전: "청라에 복음의 꽃을 피우다"
- 새가족 절차: 예배 후 담임목사 인사 → '풍성한 삶의 초대' 과정 → 새가족(하늘가족) 등록
- 2026 여름성경학교 「다윗 어드벤처」: **7.31(금)~8.2(주일)**, 유치부 대상 (notice.json 배너 end=2026-08-02)

- `site\` — 정적 홈페이지 (HTML/CSS/JS, 빌드 단계 없음). GitHub Pages 배포 예정
- `blog\` — 코드가 아닌 네이버 블로그 개편용 마크다운 템플릿·가이드 문서. `~완성본.md` 파일(11·12)은 사용자가 블로그에 그대로 복사해 붙여넣는 발행 원고
- 외부 자동화: 사용자가 dlvr.it으로 "블로그 RSS → 페이스북 페이지(청라강성교회)" 자동 게시를 직접 설정함 (2026-06-11). 페이스북은 네이버 링크 미리보기를 못 만들므로 dlvr.it에서 Post Photo·Title·URL을 켜는 방식 사용
- `2026 01 주보\`, `2026 03 오렌지카드\`, `2026 08 선포기도문\` — 교회가 매주 실제 발행해온 원본 아카이브(2025-12-28부터, hwpx/PDF/PNG). 사용자가 직접 넣은 자료이므로 절대 수정·삭제 금지. 오렌지카드=가정예배 순서지(PNG), 선포기도문=밤기도회용(hwpx/PDF). 셋 다 주일 설교와 같은 본문을 쓰는 통합 주제 구조

## 명령어

```powershell
# 로컬 미리보기 (Node 불필요 — 이 PC에는 Node가 설치되어 있지 않음)
site\미리보기.bat            # = powershell -File site\scripts\serve.ps1, http://localhost:8080

# 모바일 화면 스크린샷 (검증용)
& 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' --headless --disable-gpu `
  --screenshot=C:\Homepage\mobile.png --window-size=390,844 --hide-scrollbars `
  --virtual-time-budget=10000 'http://localhost:8080/?nocache=임의값'

# 피드 데이터 재생성 — GitHub Actions에서는 node scripts/fetch-feeds.mjs 가 돌지만
# 로컬에는 Node가 없으므로 PowerShell Invoke-RestMethod로 같은 로직을 수행해야 함
```

## 아키텍처

홈페이지는 "사용자는 유튜브·블로그만 운영하면 자동 갱신"이 핵심 설계 원칙. `index.html`은 정적 틀이고, 동적 데이터는 전부 `site\data\*.json`에서 온다:

- `posts.json` — 교회 소식 카드 (네이버 블로그 RSS에서 생성, 썸네일 포함)
- `latest-video.json` — "이번 주 말씀" 영상 (유튜브 RSS에서 최신 `[주일예배]` 영상 선별)
- `notice.json` — 고정 배너 목록 (수동 관리, `start`/`end` 기간으로 자동 표시/숨김, `"isModal": true` 옵션 부여 시 중앙 팝업 모달로 노출되며 '7일간 보지 않기' 기능 지원)
- `outreach.json` — 이웃사랑 섹션 고정 글 목록 (수동 관리 — 블로그 이웃사랑 카테고리는 2014년의 무관한 글이 섞여 있어 자동 수집하지 않기로 함)

'가정예배 · 밤기도회' 코너는 별도 데이터 파일 없이 posts.json에서 제목에 "오렌지카드"(가정예배 순서지)/"선포기도"(밤기도회)가 포함된 최신 글을 골라 표시한다. 해당 글이 없으면 안내 문구가 나오는 정상 동작.

`scripts\fetch-feeds.mjs`가 매일 GitHub Actions(`.github\workflows\update-feeds.yml`)에서 실행되어 posts.json과 latest-video.json을 갱신한다. `script.js`는 이 JSON들을 읽어 렌더링하며, fetch 실패 시(file:// 등) 내장 FALLBACK 데이터로 대체한다.

첫 화면(hero) 배경은 `site\images\hero2.jpg` (2026-07-15 교체 적용). 사진 교체는 `style.css`의 `.hero background`에서 파일명을 수정하고, `index.html`에서 `style.css?v=N` 버전을 올려야 함.

CSS 수정 시 `index.html`의 `style.css?v=N` 버전 번호를 올려 캐시를 무효화할 것.
- **모바일 반응형 최적화**: 이 홈페이지는 모바일 화면(스마트폰)에서도 완벽하게 동작하는 반응형 웹입니다. 향후 새로운 요소를 추가하거나 CSS를 수정할 때는 기존의 모바일 레이아웃(카드 세로 정렬, 메뉴 2×2 배열 등 `@media (max-width: ...)` 설정)이 절대 깨지지 않도록 모바일 뷰포트를 최우선으로 고려해야 합니다.

`site-백업-2026-07-03\`은 디자인 개편(2026-07-03) 직전의 site 폴더 백업 — 사용자가 되돌리길 원할 때만 사용.

## 검증된 연동 값 (재조사 불필요)

- 유튜브 채널: `@cnksch` = `UC7OCid3xzRUptzmHUvA7B4g` (청라강성교회TV)
- 유튜브 RSS: `https://www.youtube.com/feeds/videos.xml?channel_id=UC7OCid3xzRUptzmHUvA7B4g` (간헐적 500 → 재시도)
- 블로그: `blog.naver.com/wormwood79` / RSS: `https://rss.blog.naver.com/wormwood79.xml`
- 네이버 비공개 API (Referer 헤더 `https://m.blog.naver.com/wormwood79` 필수):
  - 글 목록: `https://m.blog.naver.com/api/blogs/wormwood79/post-list?categoryNo=0&itemCount=N&page=1` (썸네일 필드 `thumbnailUrl`, 글 수 필드는 `postCnt`)
  - 카테고리: `.../api/blogs/wormwood79/category-list`

## 함정 (이미 한 번씩 겪고 해결한 것들)

- **네이버 이미지는 Referer가 있으면 403/404로 차단** → 동적 `<img>`에 반드시 `referrerpolicy="no-referrer"` 유지
- **네이버 썸네일 URL은 `?type=` 크기 옵션 필수** — post-list API 썸네일은 `?type=w800`, og:image는 원본에 붙어 있는 `?type=w2`를 그대로 사용 (`w800`으로 바꾸면 404나는 URL도 있음)
- **유튜브 영상 임베드(`iframe`)는 153 오류(찬양 음원 저작권 차단 등)가 잦음** — `iframe` 대신 썸네일+재생버튼을 노출하고, 클릭 시 유튜브 새 창으로 이동(`target="_blank"`)하는 방식(2026-06-18 변경)을 영구적으로 유지할 것.
- **유튜브 재생목록 RSS 파싱 주의**: 유튜브 재생목록 RSS(`feeds/videos.xml?playlist_id=...`)는 영상이 오래된 순서대로 반환됨. 따라서 최신 영상을 가져오려면 첫 번째 항목이 아니라 **가장 마지막 항목**을 선택해야 함. (2026-07-15 겪음)
- 네이버 RSS는 CDATA 구조, 링크에 `?fromRss=true` 추적 파라미터가 붙음(제거 필요), 카테고리명에 `&#160;` 엔티티 혼입 가능
- `serve.ps1`은 `ContentLength64`를 설정하지 않으면 본문 0바이트로 응답함 (수정 금지)
- 이 PC는 Windows 텍스트 배율 때문에 헤드리스 스크린샷 글자가 실제보다 크게 렌더링됨 — 레이아웃은 글자 크기에 의존하지 않게(예: 모바일 메뉴는 2×2 그리드) 설계할 것
- **헤드리스 `--window-size=390`으로는 모바일 검증 불가** (2026-07-15 확인): Windows 배율 탓에 실제 CSS 뷰포트가 약 504px로 잡혀 `max-width: 480px` 모바일 미디어쿼리가 아예 안 걸리고, 화면 오른쪽이 잘려 보임(`--force-device-scale-factor`도 무시됨). 해결법: `site\`에 임시 래퍼 HTML을 만들어 `<iframe src="/" style="width:390px;height:8800px">`로 감싸 찍으면 iframe 내부가 정확히 390px 뷰포트로 렌더링됨 (창 크기는 500 이상으로, 찍은 후 래퍼 파일 삭제)
- 페이지 하단 섹션 검증 시 `#앵커`로 스크롤한 스크린샷은 **빈 화면**이 나옴(.reveal 등장 애니메이션이 발화 전) — 대신 `--window-size=390,9000`으로 전체를 찍고 System.Drawing으로 해당 영역을 크롭할 것
- 본문 HTML(m.blog/PostView)은 SPA 껍데기만 반환 — 단, **PC용 `blog.naver.com/PostView.naver?blogId=…&logNo=…`는 본문 전체 HTML을 반환**함(Referer 헤더 필요). 본문 텍스트·날짜·이미지 URL 추출은 이쪽으로
- 블로그 원본 이미지는 `postfiles.pstatic.net/...?type=w966`으로 바꾸면 고해상도로 받을 수 있음 (본문 기본은 w580)
- **.bat 파일에 한글을 넣지 말 것** — `chcp 65001`과 한글이 함께 있으면 cmd가 파일 읽는 위치가 어긋나 한글을 명령어로 실행하려다 오류남 (2026-07-03 미리보기.bat에서 발생, 한글 제거로 해결). 한글 안내문은 serve.ps1 쪽에 두기
- **serve.ps1은 반드시 UTF-8 (BOM 포함)으로 저장** — BOM 없으면 Windows PowerShell 5.1이 CP949로 읽어 한글이 전부 깨짐. 편집 후 BOM 유지 확인 필수
- 미리보기.bat 실행 시 포트 8080이 사용 중이면(이미 서버가 떠 있으면) 브라우저 창만 새로 열고 조용히 종료하는 게 정상 동작(2026-07-03 변경)
- **도메인 DNS 설정 시 주의사항**: 호스팅을 Netlify 등으로 이전할 때, 기존 호스팅 서버의 A 레코드(예: 211.43.12.102 메일플러그 등)를 반드시 삭제해야 함. 두 개가 공존하면 `ERR_CERT_COMMON_NAME_INVALID` 인증서 오류 및 접속 불량(모바일 포함) 발생. (2026-07-14 해결)
- **fetch-feeds-regex.ps1 실행 경로**: 이 스크립트는 내부적으로 `..\data\posts.json` 경로를 쓰므로, **반드시 `site\scripts` 폴더를 현재 디렉토리로 잡고 실행**해야 함. `site\` 폴더 등에서 실행하면 `site\data\`가 아닌 엉뚱한 곳에 파일이 저장되어 로컬 화면이 갱신되지 않는 현상 발생. (2026-07-14 겪음)

## 배포 및 Netlify 크레딧 관련 규칙 (중요)
- **개발 중 커밋/푸시 전략**: Netlify 무료 계정(Starter)은 매달 300 크레딧(빌드 횟수와 비례)을 제공함. 개발 초기(홈페이지 구성 단계)에는 자잘한 수정이 잦으므로, 매번 깃허브에 푸시(Push)하면 크레딧이 빠르게 소진됨.
- 따라서 사용자가 여러 수정 사항을 요구할 때는 **로컬(사용자 PC)에서만 수정을 진행**하고, 로컬 미리보기(`미리보기.bat`)로 모두 확인을 마친 후 **마지막에 한꺼번에 푸시(Push)하여 크레딧 소모를 최소화(1회)**해야 함. (사용자가 명시적으로 업로드를 요청할 때만 푸시할 것)
- 개발 완료 후 정식 운영 시에는 매일 새벽 자동 업데이트(GitHub Actions)가 하루 1회만 푸시하므로 한 달에 약 30 크레딧만 소모하여 요금 청구 위험이 없음.

## 최근 변경 사항 (2026-07-14 ~ 15)
- **지도 추가**: `index.html` 하단 오시는 길에 네이버 지도 링크 대신 구글 지도 iframe을 영구적으로 삽입하여 화면에 직접 지도가 보이도록 수정.
- **교통편 및 주차 정보 구체화**: 43번 버스(교회 앞 하차) 및 주변 버스 노선 명시, 지하 주차장이 아닌 '1층 주차장'으로 안내 수정.
- **배포 및 업데이트 계획 기록**: 로컬에서 수정한 내역을 바로 라이브에 반영하려면 Netlify 대시보드(Deploys)에 `site` 폴더를 통째로 다시 '드래그 앤 드롭'하여 수동 업데이트 가능. 현재는 GitHub에 연동되어 푸시 시 자동 배포됨.
- **공동체성경읽기 로직 수정**: 최신 영상을 정상적으로 불러오기 위해 재생목록 파싱 시 마지막 항목을 선택하도록 수정 및 Netlify 크레딧 절약을 위한 로컬 배치(batch) 수정 규칙 확립.
- **메인 비주얼(hero) 이미지 변경 (2026-07-15, 로컬만 반영·미배포)**: `site\images\hero2.jpg`로 배경 사진 교체 및 `style.css?v=9`로 캐시 무효화.
- **비전 섹션 간결화 (2026-07-15, 로컬만 반영·미배포)**: hanabokdna.org/about 스타일을 참고해 '교회 비전 및 핵심 가치' 섹션 축소 — 5대 가치 설명을 한 문장씩으로 줄이고, 아이콘을 제목 옆 인라인으로, 분류(전도 등)는 제목 우측 알약 배지로 이동. 로고 이미지 120px로 축소, 로고 설명 두 문장으로 정리("로고에 담긴 의미"). 여백·글자 크기 축소로 섹션 높이 약 절반. style.css?v=8로 캐시 버전 올림. 모바일(390px iframe 기법)·PC 스크린샷 검증 완료.
- **블로그 연동 및 디자인 업그레이드 (2026-07-15, 로컬만 반영·미배포)**:
  - `fw-grid` 코너 이름을 "주간 신앙 가이드"로 변경하고 `[설교칼럼]` 카드 추가.
  - 기존 유튜브에서 불러오던 `[공동체성경읽기]`를 블로그 글 연동으로 구조 변경 (script.js 수정).
  - 이미지 없는 블로그 카드의 썸네일(`.post-thumb`)을 칙칙한 단색에서 카테고리별 맞춤형 그라데이션 및 도트 패턴 오버레이로 프리미엄(Glassmorphism) 스타일로 대폭 개선.
  - 메인 및 네비게이션의 "처음 오셨나요?" 버튼 링크를 블로그의 새가족 안내 게시물(URL 직접 지정)로 연결.

## 관련 문서

- `README.md` — 사용자용 진행 체크리스트·운영 루틴·배너 관리법 (수정 시 사용자 눈높이 유지)
- 벤치마크 조사·교회 현황 진단은 Claude 메모리(`church-website-research`, `cheongna-church-diagnosis` 등)에 있음
