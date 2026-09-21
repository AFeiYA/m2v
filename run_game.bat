@echo off
title 3D 节奏飞车 — 一键启动器
color 0B
echo ====================================================
echo      🎤 M2V 3D 节奏飞车 (Dreaming Craftsmanship Ride)
echo ====================================================
echo.
echo [1/3] 正在进入播放器目录...
cd /d "%~dp0\frontend\player"

echo [2/3] 正在启动本地游戏服务器 (Port 4567)...
:: Start node server.js in background
start "" /b node server.js

echo.
echo [3/3] 正在为您在浏览器中打开 3D 航线...
timeout /t 2 /nobreak >nul
start http://localhost:4567/game.html

echo.
echo ====================================================
echo   🚀 游戏服务已成功在后台运行！
echo   🌐 请在浏览器中畅玩，不要关闭此命令行窗口。
echo   ❌ 退出游戏时，请按 Ctrl+C 或直接关闭此窗口以终止服务器。
echo ====================================================
echo.
pause
