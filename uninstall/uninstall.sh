#!/bin/bash
set -e

sudo -n rm -f /etc/cron.d/loxberryhostbackup 2>/dev/null || rm -f /etc/cron.d/loxberryhostbackup 2>/dev/null || true
sudo -n rm -f /etc/sudoers.d/loxberryhostbackup 2>/dev/null || rm -f /etc/sudoers.d/loxberryhostbackup 2>/dev/null || true
sudo -n rm -f /var/lock/loxberryhostbackup.lock 2>/dev/null || rm -f /var/lock/loxberryhostbackup.lock 2>/dev/null || true
exit 0
