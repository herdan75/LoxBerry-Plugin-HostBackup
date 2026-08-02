#!/bin/bash
set -e

sudo -n rm -f /etc/cron.d/loxberryhostbackup 2>/dev/null || rm -f /etc/cron.d/loxberryhostbackup 2>/dev/null || true
sudo -n rm -f /etc/sudoers.d/loxberryhostbackup 2>/dev/null || rm -f /etc/sudoers.d/loxberryhostbackup 2>/dev/null || true
sudo -n rm -f /var/lock/loxberryhostbackup.lock 2>/dev/null || rm -f /var/lock/loxberryhostbackup.lock 2>/dev/null || true
sudo -n rm -f /var/lock/loxberryhostbackup.operation.lock 2>/dev/null || rm -f /var/lock/loxberryhostbackup.operation.lock 2>/dev/null || true
sudo -n rm -f /usr/local/sbin/loxberryhostbackup-sudo 2>/dev/null || rm -f /usr/local/sbin/loxberryhostbackup-sudo 2>/dev/null || true
sudo -n rm -rf --one-file-system -- /var/lib/loxberryhostbackup 2>/dev/null || rm -rf --one-file-system -- /var/lib/loxberryhostbackup 2>/dev/null || true
exit 0
