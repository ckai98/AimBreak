@echo off
chcp 65001 >nul
REM ============================================
REM 办公室反应训练器 - PyInstaller 打包脚本
REM 用法：双击运行或在终端执行 build.bat
REM 依赖：pip install pyinstaller PySide6
REM 产物：dist\OfficeAimTrainer.exe
REM ============================================

echo [1/2] 开始打包 OfficeAimTrainer ...
pyinstaller --onefile --windowed --name OfficeAimTrainer main.py

if errorlevel 1 (
    echo.
    echo [失败] 打包过程中出错，请检查上方日志。
    exit /b 1
)

echo.
echo [2/2] 打包完成。
echo 产物路径: dist\OfficeAimTrainer.exe
echo 数据目录: %%LOCALAPPDATA%%\OfficeAimTrainer\OfficeAimTrainer\
echo   （stats.json 与 QSettings 配置运行时写入此处）
echo.
pause
