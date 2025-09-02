@echo off
chcp 65001 >nul
echo ========================================
echo   Nano banana批量出图工具 - 优化版界面
echo ========================================
echo.
echo ✨ 特性：
echo • 统一设置管理中心
echo • 简洁主界面设计
echo • 三合一弹窗管理（配置+风格库+参考图）
echo.
echo 正在启动优化版界面...
echo.
if "%1" == "h" goto begin
mshta vbscript:createobject("wscript.shell").run("""%~nx0"" h",0)(window.close)&&exit
:begin
pythonw main.py