#!/bin/bash

set -e  # Exit on error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34mg'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="/home/darkus/Desktop/AdviseProject/ai-backend"
VENV_DIR="${PROJECT_DIR}/.venv"
LOG_DIR="${PROJECT_DIR}/logs"
PID_DIR="${PROJECT_DIR}/pids"

# PID files
FASTAPI_PID="${PID_DIR}/fastapi.pid"
CELERY_PID="${PID_DIR}/celery.pid"

# Log files
FASTAPI_LOG="${LOG_DIR}/fastapi.log"
CELERY_LOG="${LOG_DIR}/celery.log"

# Print header
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Starting AI WhatsApp Backend${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Create directories if they don't exist
mkdir -p "${LOG_DIR}"
mkdir -p "${PID_DIR}"

# Change to project directory
cd "${PROJECT_DIR}"

# Check if services are already running
if [ -f "${FASTAPI_PID}" ] && kill -0 $(cat "${FASTAPI_PID}") 2>/dev/null; then
    echo -e "${YELLOW}⚠️  FastAPI is already running (PID: $(cat ${FASTAPI_PID}))${NC}"
else
    echo -e "${GREEN}Starting FastAPI server...${NC}"
    
    # Activate virtual environment and start FastAPI
    source "${VENV_DIR}/bin/activate"
    
    nohup python run_server.py > "${FASTAPI_LOG}" 2>&1 &
    FASTAPI_PID_NUM=$!
    
    echo "${FASTAPI_PID_NUM}" > "${FASTAPI_PID}"
    
    # Wait a moment and verify it started
    sleep 2
    if kill -0 "${FASTAPI_PID_NUM}" 2>/dev/null; then
        echo -e "${GREEN}✅ FastAPI started successfully (PID: ${FASTAPI_PID_NUM})${NC}"
        echo -e "   Log: ${FASTAPI_LOG}"
    else
        echo -e "${RED}❌ FastAPI failed to start${NC}"
        echo -e "   Check log: ${FASTAPI_LOG}"
        rm -f "${FASTAPI_PID}"
        exit 1
    fi
fi

echo ""

# Start Celery
if [ -f "${CELERY_PID}" ] && kill -0 $(cat "${CELERY_PID}") 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Celery is already running (PID: $(cat ${CELERY_PID}))${NC}"
else
    echo -e "${GREEN}Starting Celery worker...${NC}"
    
    # Activate virtual environment and start Celery
    source "${VENV_DIR}/bin/activate"
    
    nohup celery -A tasks worker \
        --loglevel=info \
        --concurrency=4 \
        --queues=default,state,messages,status,media \
        --max-tasks-per-child=100 \
        > "${CELERY_LOG}" 2>&1 &
    
    CELERY_PID_NUM=$!
    
    echo "${CELERY_PID_NUM}" > "${CELERY_PID}"
    
    # Wait a moment and verify it started
    sleep 3
    if kill -0 "${CELERY_PID_NUM}" 2>/dev/null; then
        echo -e "${GREEN}✅ Celery started successfully (PID: ${CELERY_PID_NUM})${NC}"
        echo -e "   Log: ${CELERY_LOG}"
    else
        echo -e "${RED}❌ Celery failed to start${NC}"
        echo -e "   Check log: ${CELERY_LOG}"
        rm -f "${CELERY_PID}"
        exit 1
    fi
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ All services started successfully!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Service Status:"
echo -e "  FastAPI: ${GREEN}Running${NC} (PID: $(cat ${FASTAPI_PID}))"
echo -e "  Celery:  ${GREEN}Running${NC} (PID: $(cat ${CELERY_PID}))"
echo ""
echo -e "Access:"
echo -e "  HTTP:  http://0.0.0.0:5000"
echo -e "  HTTPS: https://0.0.0.0:5000 ${YELLOW}(if SSL configured)${NC}"
echo -e "  Docs:  http://0.0.0.0:5000/docs"
echo ""
echo -e "Logs:"
echo -e "  FastAPI: tail -f ${FASTAPI_LOG}"
echo -e "  Celery:  tail -f ${CELERY_LOG}"
echo ""
echo -e "To stop services: ${YELLOW}./stop_services.sh${NC}"
echo ""
