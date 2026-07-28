@echo off
title Verify the endpoint host allowlist
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo ============================================================
echo  Runs the new guard's tests, then the full suite to prove
echo  nothing else broke. Read-only - no network, no GPU.
echo ============================================================
echo.

echo ---- 1. The new guard (6 tests) ----
python -m pytest tests\test_net_guard.py -v
echo.

echo ---- 2. Everything else still passes ----
python -m pytest tests -q
echo.

echo ============================================================
echo  Both green means the fix is in and nothing regressed.
echo  Copy the results above back to Claude.
echo ============================================================
echo.
pause
