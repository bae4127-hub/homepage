# 홈페이지 로컬 미리보기 서버 (설치 불필요)
# 실행: site 폴더의 "미리보기.bat" 더블클릭
$port = 8080
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$port/")
try { $listener.Start() } catch {
  Write-Host "포트 $port 가 이미 사용 중입니다. 이미 미리보기가 실행 중인지 확인하세요."
  Read-Host "엔터를 누르면 닫힙니다"
  exit 1
}

$mime = @{
  '.html' = 'text/html; charset=utf-8'
  '.css'  = 'text/css; charset=utf-8'
  '.js'   = 'text/javascript; charset=utf-8'
  '.json' = 'application/json; charset=utf-8'
  '.png'  = 'image/png'
  '.jpg'  = 'image/jpeg'
  '.jpeg' = 'image/jpeg'
  '.gif'  = 'image/gif'
  '.svg'  = 'image/svg+xml'
  '.ico'  = 'image/x-icon'
}

Start-Process "http://localhost:$port/"
Write-Host ""
Write-Host "  ✅ 홈페이지 미리보기 실행 중:  http://localhost:$port/"
Write-Host "  ❌ 끝내려면 이 검은 창을 닫으세요."
Write-Host ""

while ($listener.IsListening) {
  $ctx = $listener.GetContext()
  try {
    $path = [System.Uri]::UnescapeDataString($ctx.Request.Url.AbsolutePath)
    if ($path -eq '/') { $path = '/index.html' }
    $file = Join-Path $root ($path.TrimStart('/') -replace '/', '\')
    $full = $null
    if (Test-Path $file -PathType Leaf) { $full = (Resolve-Path $file).Path }
    if ($full -and $full.StartsWith($root)) {
      $bytes = [System.IO.File]::ReadAllBytes($full)
      $ext = [System.IO.Path]::GetExtension($full).ToLower()
      if ($mime.ContainsKey($ext)) { $ctx.Response.ContentType = $mime[$ext] }
      else { $ctx.Response.ContentType = 'application/octet-stream' }
      $ctx.Response.AddHeader('Cache-Control', 'no-store') # 수정사항이 새로고침에 바로 반영되도록
      $ctx.Response.ContentLength64 = $bytes.Length
      $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    } else {
      $ctx.Response.StatusCode = 404
    }
  } catch { $ctx.Response.StatusCode = 500 }
  $ctx.Response.Close()
}
