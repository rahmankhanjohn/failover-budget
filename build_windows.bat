@echo off
REM Build a single-file Windows executable: dist\failover-budget.exe
REM Requires Python 3.9+ with pip. Run from the repository root.

python -m pip install --upgrade pyinstaller
python -m PyInstaller --onefile --name failover-budget --clean --noconfirm failover_budget.py

echo.
echo Built: dist\failover-budget.exe
echo Run:   dist\failover-budget.exe --probe-interval 5 --fall-threshold 3 --ttl 600 --cache-propagation 60
