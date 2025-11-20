#!/bin/bash
# Stop AI WhatsApp Backend Services on EC2
# Usage: ./stop_services.sh

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="/home/darkus/Desktop/AdviseProject/ai-backend"
PID_DIR="${PROJECT_DIR}/pids"

# PID files
FASTAPI_PID="${PID_DIR}/fastapi.pid"
CELERY_PID="${PID_DIR}/celery.pid"

# Print header
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Stopping AI WhatsApp Backend${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

STOPPED_COUNT=0
FAILED_COUNT=0

# Stop FastAPI
if [ -f "${FASTAPI_PID}" ]; then
    PID=$(cat "${FASTAPI_PID}")
    
    if kill -0 "${PID}" 2>/dev/null; then
        echo -e "${YELLOW}Stopping FastAPI (PID: ${PID})...${NC}"
        
        # Try graceful shutdown first
        kill -TERM "${PID}" 2>/dev/null || true
        
        # Wait up to 10 seconds for graceful shutdown
        for i in {1..10}; do
            if ! kill -0 "${PID}" 2>/dev/null; then
                echo -e "${GREEN}✅ FastAPI stopped gracefully${NC}"
                rm -f "${FASTAPI_PID}"
                STOPPED_COUNT=$((STOPPED_COUNT + 1))
                break
            fi
            sleep 1
        done
        
        # Force kill if still running
        if kill -0 "${PID}" 2>/dev/null; then
            echo -e "${YELLOW}⚠️  Force killing FastAPI...${NC}"
            kill -9 "${PID}" 2>/dev/null || true
            sleep 1
            
            if ! kill -0 "${PID}" 2>/dev/null; then
                echo -e "${GREEN}✅ FastAPI stopped (forced)${NC}"
                rm -f "${FASTAPI_PID}"
                STOPPED_COUNT=$((STOPPED_COUNT + 1))
            else
                echo -e "${RED}❌ Failed to stop FastAPI${NC}"
                FAILED_COUNT=$((FAILED_COUNT + 1))
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  FastAPI PID file exists but process not running${NC}"
        rm -f "${FASTAPI_PID}"
    fi
else
    echo -e "${YELLOW}⚠️  FastAPI is not running${NC}"
fi

echo ""

# Stop Celery
if [ -f "${CELERY_PID}" ]; then
    PID=$(cat "${CELERY_PID}")
    
    if kill -0 "${PID}" 2>/dev/null; then
        echo -e "${YELLOW}Stopping Celery (PID: ${PID})...${NC}"
        
        # Try graceful shutdown first (TERM signal)
        kill -TERM "${PID}" 2>/dev/null || true
        
        # Wait up to 15 seconds for graceful shutdown (Celery needs more time)
        for i in {1..15}; do
            if ! kill -0 "${PID}" 2>/dev/null; then
                echo -e "${GREEN}✅ Celery stopped gracefully${NC}"
                rm -f "${CELERY_PID}"
                STOPPED_COUNT=$((STOPPED_COUNT + 1))
                break
            fi
            sleep 1
        done
        
        # Force kill if still running
        if kill -0 "${PID}" 2>/dev/null; then
            echo -e "${YELLOW}⚠️  Force killing Celery...${NC}"
            kill -9 "${PID}" 2>/dev/null || true
            sleep 1
            
            if ! kill -0 "${PID}" 2>/dev/null; then
                echo -e "${GREEN}✅ Celery stopped (forced)${NC}"
                rm -f "${CELERY_PID}"
                STOPPED_COUNT=$((STOPPED_COUNT + 1))
            else
                echo -e "${RED}❌ Failed to stop Celery${NC}"
                FAILED_COUNT=$((FAILED_COUNT + 1))
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  Celery PID file exists but process not running${NC}"
        rm -f "${CELERY_PID}"
    fi
else
    echo -e "${YELLOW}⚠️  Celery is not running${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"

if [ ${FAILED_COUNT} -eq 0 ]; then
    echo -e "${GREEN}✅ All services stopped successfully!${NC}"
else
    echo -e "${RED}⚠️  ${FAILED_COUNT} service(s) failed to stop${NC}"
fi

echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Stopped: ${STOPPED_COUNT}"
echo -e "Failed:  ${FAILED_COUNT}"
echo ""
echo -e "To start services: ${YELLOW}./start_services.sh${NC}"
echo ""
