@echo off
rem 在庫管理システムを開く（初めての場合は 使い方.md の「準備」を先に）
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 先に 使い方.md の「準備」の手順を行ってください。
  pause
  exit /b 1
)
echo 在庫管理システムを起動しています。少しするとブラウザが開きます。
echo 終わるときは、この窓を閉じてください。
rem 起動を少し待ってからブラウザで開く
start "" /b cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app\streamlit_app.py
