[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$OutPosts = "..\data\posts.json"
$OutVideo = "..\data\latest-video.json"
$BlogRssUrl = "https://rss.blog.naver.com/wormwood79.xml"
$YtRssUrl = "https://www.youtube.com/feeds/videos.xml?channel_id=UC7OCid3xzRUptzmHUvA7B4g"
$HideCategories = @("낙서장", "일상기록", "책읽기")

Write-Host "블로그 RSS 가져오는 중..."
$blogRss = Invoke-RestMethod -Uri $BlogRssUrl -Headers @{"User-Agent"="Mozilla/5.0 (church-homepage-bot)"}

$items = @()
$count = 0

foreach ($item in $blogRss.rss.channel.item) {
    if ($count -ge 12) { break }
    $cat = $item.category
    if ($HideCategories -contains $cat) { continue }
    
    $link = $item.link -replace "\?fromRss=true.*$", ""
    $link = $link -replace "&amp;", "&"
    $dateObj = [datetime]::Parse($item.pubDate)
    $dateStr = $dateObj.ToString("yyyy-MM-dd")
    
    $postObj = [PSCustomObject]@{
        title = $item.title
        link = $link
        date = $dateStr
        category = $cat
        image = $null
    }
    $items += $postObj
    $count++
}

Write-Host "네이버 썸네일 API 가져오는 중..."
$naverHeaders = @{
    "User-Agent" = "Mozilla/5.0"
    "Referer" = "https://m.blog.naver.com/wormwood79"
}
$thumbMap = @{}
try {
    $listRes = Invoke-RestMethod -Uri "https://m.blog.naver.com/api/blogs/wormwood79/post-list?categoryNo=0&itemCount=30&page=1" -Headers $naverHeaders
    if ($listRes.result.items) {
        foreach ($it in $listRes.result.items) {
            if ($it.hasThumbnail -and $it.thumbnailUrl) {
                $logNoStr = [string]$it.logNo
                $thumbMap[$logNoStr] = "$($it.thumbnailUrl)?type=w800"
            }
        }
    }
} catch {
    Write-Host "썸네일 API 오류: $_"
}

foreach ($p in $items) {
    if ($p.link -match "/(\d+)$") {
        $logNo = $matches[1]
        if ($thumbMap.ContainsKey($logNo)) {
            $p.image = $thumbMap[$logNo]
        } else {
            try {
                $html = Invoke-RestMethod -Uri "https://m.blog.naver.com/wormwood79/$logNo" -Headers $naverHeaders
                if ($html -match "(?:youtu\.be/|youtube\.com/(?:embed/|watch\?v=|shorts/))([\w-]{11})") {
                    $p.image = "https://i.ytimg.com/vi/$($matches[1])/hqdefault.jpg"
                }
            } catch {}
        }
    }
}

if (-not (Test-Path "..\data")) {
    New-Item -ItemType Directory -Path "..\data" | Out-Null
}

$items | ConvertTo-Json -Depth 5 -Compress:$false | Set-Content -Path $OutPosts -Encoding UTF8
Write-Host "완료: posts.json에 $($items.Count)개 글 저장"

Write-Host "유튜브 RSS 가져오는 중..."
$ytRss = Invoke-RestMethod -Uri $YtRssUrl -Headers @{"User-Agent"="Mozilla/5.0 (church-homepage-bot)"}

$videos = @()
foreach ($entry in $ytRss.feed.entry) {
    $published = $entry.published -replace "T.*", ""
    $videos += [PSCustomObject]@{
        videoId = $entry.videoId
        title = $entry.title
        date = $published
    }
}

$latest = $null
$sundayWorship = $videos | Where-Object { $_.title -match "주일예배" }
if ($sundayWorship) {
    $latest = $sundayWorship[0]
} else {
    $nonShorts = $videos | Where-Object { $_.title -notmatch "#shorts" }
    if ($nonShorts) {
        $latest = $nonShorts[0]
    } elseif ($videos.Count -gt 0) {
        $latest = $videos[0]
    }
}

if ($latest) {
    $latest | ConvertTo-Json -Depth 5 -Compress:$false | Set-Content -Path $OutVideo -Encoding UTF8
    Write-Host "완료: latest-video.json에 유튜브 저장"
}
