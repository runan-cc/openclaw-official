#!/bin/bash
cd "$(dirname "$0")"
exec "$(dirname "$0")/openclaw" "$@"
