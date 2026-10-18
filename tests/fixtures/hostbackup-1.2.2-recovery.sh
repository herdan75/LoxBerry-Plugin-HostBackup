# Historical regression fixture, never a standalone or installed program.
# Source: v1.2.2-beta, commit 9322736936ad0b18d00c54f373b4babfd44f8bd9,
# bin/hostbackup.sh. Exact LF-normalized function bodies, SHA256:
# restart_journal_retry_type: b050afe7151b01f6ce5289c5f3ed462186604220122af7132837b870b611d46a
# recover_restart_journals: dec0bd7610dd2d8cfa721a473560145c9570f337cf1e1c58f8978e358953e206
# All Docker commands in the installer integration are redirected to a stub.

restart_journal_retry_type() {
  local state_dir="$1" requested_type="$2" pending type identity phase failed=0
  pending="$(restart_journal_update "$state_dir" pending)" || return 20
  while IFS=$'\t' read -r type identity phase; do
    [ "$type" = "$requested_type" ] || continue
    log "Recovering $type $identity (journal state: $phase)"
    if [ "$type" = docker ]; then
      if ! command -v docker >/dev/null 2>&1; then failed=1; continue; fi
      if [ "$(docker inspect --format '{{.State.Running}}' "$identity" 2>/dev/null || true)" != true ]; then
        if command -v timeout >/dev/null 2>&1; then timeout 45 docker start "$identity" || true;
        else docker start "$identity" || true; fi
      fi
      if [ "$(docker inspect --format '{{.State.Running}}' "$identity" 2>/dev/null || true)" != true ]; then
        log "ERROR: Docker container $identity did not restart; journal retained for retry"; failed=1; continue
      fi
    else
      if ! command -v systemctl >/dev/null 2>&1; then failed=1; continue; fi
      if ! systemctl is-active --quiet "$identity" 2>/dev/null; then
        if command -v timeout >/dev/null 2>&1; then timeout 45 systemctl start "$identity" || true;
        else systemctl start "$identity" || true; fi
      fi
      if ! systemctl is-active --quiet "$identity" 2>/dev/null; then
        log "ERROR: Systemd service $identity did not restart; journal retained for retry"; failed=1; continue
      fi
    fi
    restart_journal_update "$state_dir" restarted "$type" "$identity" || failed=1
  done <<< "$pending"
  return "$failed"
}

recover_restart_journals() {
  require_root_for_write || return $?
  local state_dir task log_file failed=0 busy_notice=report lock_status=0
  case "$#:${1:-}" in
    0:) ;;
    1:--scheduled) busy_notice=quiet-busy ;;
    *) echo "Usage: recover-services [--scheduled]" >&2; return 64 ;;
  esac
  acquire_operation_lock exclusive "$busy_notice" || lock_status=$?
  if [ "$lock_status" -ne 0 ]; then
    # Cron will retry in five minutes. Do not touch journals or active tasks.
    [ "$lock_status" -ne 5 ] || [ "$busy_notice" != quiet-busy ] || return 0
    return "$lock_status"
  fi
  for state_dir in "$RESTART_JOURNAL_DIR"/*; do
    [ -d "$state_dir" ] && [ ! -L "$state_dir" ] || continue
    task="$(basename -- "$state_dir")"
    valid_task_name "$task" || { failed=1; continue; }
    task_process_is_current "$task" && continue
    log_file="$TASK_LOG_DIR/$task"
    prepare_log_file "$log_file" append || { failed=1; continue; }
    log "Recovering interrupted task $task from local restart journal" | tee -a "$log_file"
    if start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file" && restart_journal_finish "$state_dir"; then
      task_state_write "$task" failed recovered_after_interruption "$log_file" 0 20 || failed=1
    else
      task_state_write "$task" failed cleanup_failed "$log_file" 0 20 || true
      failed=1
    fi
  done
  return "$failed"
}

