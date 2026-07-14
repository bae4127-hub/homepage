@echo off
chcp 65001 >nul
title 청라강성교회 홈페이지 미리보기
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\serve.ps1"
