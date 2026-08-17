#!/bin/bash
echo "=== VITE LOG ==="
cat /tmp/vite_dev.log 2>/dev/null || echo "no log"
echo "=== PROCESSES ==="
ps -ef | grep '[v]ite' || echo "no vite"
echo "=== MEMORY ==="
free -h 2>/dev/null || echo "free unavailable"
echo "=== PORT 5899 ==="
ss -ltn 2>/dev/null | grep 5899 || echo "port 5899 not listening"
echo "=== DISK ==="
df -h /tmp 2>/dev/null | tail -1
