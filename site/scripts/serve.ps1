# 홈페이지 로컬 미리보기 서버 (설치 불필요)
# 실행: site 폴더의 "미리보기.bat" 더블클릭
# 주의: 이 파일은 반드시 "UTF-8 (BOM 포함)"으로 저장해야 한글이 깨지지 않음
try { $Host.UI.RawUI.WindowTitle = '청라강성교회 홈페이지 미리보기' } catch {}
$port = 8080
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$port/")
try { $listener.Start() } catch {
  # 이미 미리보기가 켜져 있는 경우 — 브라우저 창만 새로 열어주면 됨
  Write-Host ""
  Write-Host "  미리보기가 이미 실행 중입니다. 브라우저 창을 새로 엽니다."
  Start-Process "http://localhost:$port/"
  Start-Sleep -Seconds 3
  exit 0
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
