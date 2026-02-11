#!/bin/bash
cd "$(dirname "$0")"

case "$1" in
  start)
    # 기존 프로세스 확인
    if pgrep -f "stock-briefing/.venv/bin/python main.py" > /dev/null; then
      echo "이미 실행 중입니다. 'run.sh restart'를 사용하세요."
      exit 1
    fi
    nohup .venv/bin/python main.py > server.log 2>&1 &
    echo "서버 시작 (PID: $!)"
    ;;
  stop)
    pkill -f "stock-briefing/.venv/bin/python main.py" 2>/dev/null
    pkill -f "stock-briefing/.venv/bin/uvicorn" 2>/dev/null
    echo "서버 종료"
    ;;
  restart)
    $0 stop
    sleep 1
    $0 start
    ;;
  status)
    pgrep -af "stock-briefing/.venv/bin/python main.py" || echo "실행 중인 서버 없음"
    ;;
  log)
    tail -f server.log
    ;;
  *)
    echo "사용법: ./run.sh {start|stop|restart|status|log}"
    ;;
esac
