#!/bin/bash
cd "$(dirname "$0")"

PID_FILE=".server.pid"

case "$1" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "이미 실행 중입니다 (PID: $(cat "$PID_FILE")). 'run.sh restart'를 사용하세요."
      exit 1
    fi
    nohup .venv/bin/python main.py > server.log 2>&1 &
    echo $! > "$PID_FILE"
    echo "서버 시작 (PID: $!)"
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      pid=$(cat "$PID_FILE")
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        echo "서버 종료 (PID: $pid)"
      else
        echo "프로세스 이미 종료됨"
      fi
      rm -f "$PID_FILE"
    else
      # fallback: 포트로 찾기
      pids=$(lsof -ti :8000 2>/dev/null)
      if [ -n "$pids" ]; then
        kill $pids 2>/dev/null
        echo "서버 종료 (PID: $pids)"
      else
        echo "실행 중인 서버 없음"
      fi
    fi
    ;;
  restart)
    $0 stop
    sleep 1
    $0 start
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "실행 중 (PID: $(cat "$PID_FILE"))"
    else
      echo "실행 중인 서버 없음"
    fi
    ;;
  log)
    tail -f server.log
    ;;
  *)
    echo "사용법: ./run.sh {start|stop|restart|status|log}"
    ;;
esac
