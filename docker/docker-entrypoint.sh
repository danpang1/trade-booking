#!/usr/bin/env bash

set -e

RUNTIME_DIR=${RUNTIME_DIR:-/opt/app}
VAULT_DIR=${VAULT_DIR:-/vault/secrets}

log () {
  echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

if [ ! -z ${VENV_DIR+x} ]; then
  . $VENV_DIR/bin/activate
fi

if [ -d "$VAULT_DIR" ]; then
  for f in $(find $VAULT_DIR -name '*.sh'); do
    log "Sourcing vault file $f.";
    source $f;
  done
fi

if [ -d "$RUNTIME_DIR" ]; then
  cd $RUNTIME_DIR
  log "Running in `pwd`."
fi

if [ "$#" -gt 0 ]; then
  log "Handling \"$@\" input commands."

  # In case we have multiple commands, we eval the first ones and exec the last one.
  # The exec replaces the current program.
  IFS=';' read -a cmds <<<$@
  log "Processing #${#cmds[@]} commands in total."

  if [ "${#cmds[@]}" -gt 1 ]; then
    for cmd in "${cmds[@]::${#cmds[@]}-1}"; do
      log "Evaluating: $cmd"
      eval "$cmd"
    done
  fi

  log "Executing: ${cmds[-1]}."
  exec ${cmds[-1]}
fi

log "Exiting."
