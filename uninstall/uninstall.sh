#!/bin/bash
set -e

sudo -n rm -f /etc/cron.d/loxberryhostbackup 2>/dev/null || rm -f /etc/cron.d/loxberryhostbackup 2>/dev/null || true
exit 0
