$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$OutPosts = "..\data\posts.json"
$OutVideo = "..\data\latest-video.json"

Write-Host "Fetching Blog RSS..."
$blogRssStr = (Invoke-WebRequest -Uri "https://rss.blog.naver.com/wormwood79.xml" -Headers @{"User-Agent"="Mozilla/5.0"} -UseBasicParsing).Content

$HideCategories = @("낙서장", "일상기록", "책읽기")

function Pick([string]$xml, [string]$tag) {
    if ($xml -match "<$tag>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</$tag>") {
        $val = $matches[1].Trim()
        $val = $val -replace "&#(\d+);", { [char][int]$args[0].Groups[1].Value }
        $val = $val -replace "&amp;", "&"
        $val = $val -replace "&lt;", "<"
        $val = $val -replace "&gt;", ">"
        $val = $val -replace "&quot;", "`""
        $val = $val -replace "&apos;", "'"
        return $val
    }
    return ""
}

$items = @()
$matches_list = [regex]::Matches($blogRssStr, "<item>([\s\S]*?)</item>")
foreach ($m in $matches_list) {
    $it = $m.Groups[1].Value
    $cat = Pick -xml $it -tag "category"
    if ($HideCategories -contains $cat) { continue }
    
    $title = Pick -xml $it -tag "title"
    if ([string]::IsNullOrWhiteSpace($title)) { continue }
    
    $link = Pick -xml $it -tag "link"
    $link = $link -replace "\?fromRss=true.*$", ""
    $link = $link -replace "&amp;", "&"
    
    $pubDate = Pick -xml $it -tag "pubDate"
    $dateStr = ""
    try {
        $dateObj = [datetime]::Parse($pubDate)
        $dateStr = $dateObj.ToString("yyyy-MM-dd")
    } catch { }

    $postObj = [ordered]@{
        title = $title
        link = $link
        date = $dateStr
        category = $cat
        image = $null
    }
    $items += $postObj
    if ($items.Count -ge 12) { break }
}

Write-Host "Fetching Thumbnails..."
$naverHeaders = @{
    "User-Agent" = "Mozilla/5.0"
    "Referer" = "https://m.blog.naver.com/wormwood79"
}
$thumbMap = @{}
try {
    $listResStr = (Invoke-WebRequest -Uri "https://m.blog.naver.com/api/blogs/wormwood79/post-list?categoryNo=0&itemCount=30&page=1" -Headers $naverHeaders -UseBasicParsing).Content
    $listRes = $listResStr | ConvertFrom-Json
    if ($listRes.result.items) {
        foreach ($it in $listRes.result.items) {
            if ($it.hasThumbnail -and $it.thumbnailUrl) {
                $logNoStr = [string]$it.logNo
                $thumbMap[$logNoStr] = "$($it.thumbnailUrl)?type=w800"
            }
        }
    }
} catch {
    Write-Host "Thumbnail API Error: $_"
}

foreach ($p in $items) {
    if ($p.link -match "/(\d+)$") {
        $logNo = $matches[1]
        if ($thumbMap.ContainsKey($logNo)) {
            $p.image = $thumbMap[$logNo]
        } else {
            try {
                $html = (Invoke-WebRequest -Uri "https://m.blog.naver.com/wormwood79/$logNo" -Headers $naverHeaders -UseBasicParsing).Content
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

$items | ConvertTo-Json -Depth 5 | Set-Content -Path $OutPosts -Encoding UTF8
Write-Host "Saved $($items.Count) posts to posts.json"

Write-Host "Fetching YouTube RSS..."
$ytRssStr = (Invoke-WebRequest -Uri "https://www.youtube.com/feeds/videos.xml?channel_id=UC7OCid3xzRUptzmHUvA7B4g" -Headers @{"User-Agent"="Mozilla/5.0"} -UseBasicParsing).Content

$videos = @()
$ytMatches = [regex]::Matches($ytRssStr, "<entry>([\s\S]*?)</entry>")
foreach ($m in $ytMatches) {
    $e = $m.Groups[1].Value
    $videoId = Pick -xml $e -tag "yt:videoId"
    if (-not $videoId) { continue }
    $title = Pick -xml $e -tag "title"
    $published = Pick -xml $e -tag "published"
    $published = $published -replace "T.*", ""
    
    $videos += [ordered]@{
        videoId = $videoId
        title = $title
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
    $latest | ConvertTo-Json -Depth 5 | Set-Content -Path $OutVideo -Encoding UTF8
    Write-Host "Saved latest video to latest-video.json"
}
