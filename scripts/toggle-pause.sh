#!/bin/bash
pid_file="/tmp/oled-saver-$(id -u).pid"
if [ -f "$pid_file" ]; then
    kill -USR1 "$(cat "$pid_file")" 2>/dev/null
fi
