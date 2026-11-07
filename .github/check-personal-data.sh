#!/bin/sh
# Fails if tracked files contain private LAN addresses or e-mail addresses (personal data must never be committed).
# Allowed: documentation examples (192.168.1.x, 203.0.113.x, example.org), CIDR networks (x.x.0.0/16), noreply.
PATTERN='\b(192\.168|10\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]*[a-z]{2,}\b'
ALLOW='noreply@|users\.noreply|user@|usuario@|you@|192\.168\.1\.[0-9]|\.0\.0/[0-9]|\.0/24|example\.(org|com)|ejemplo\.org|@anthropic-ai/|git@github\.com'
found=$(git ls-files -z | xargs -0 grep -nHIE "$PATTERN" 2>/dev/null | grep -vE "$ALLOW")
if [ -n "$found" ]; then
  echo "$found"
  echo "::error::Possible personal data found (private IPs or e-mail addresses). Use 192.168.1.x / example.org."
  exit 1
fi
echo "No personal data found."
