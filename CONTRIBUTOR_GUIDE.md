# Contributor Guide - AI WhatsApp Backend

Welcome! This guide will help you get started as a contributor to this project that's already deployed in production on AWS.

---

## 🎯 Overview

You've pulled the project from Git and it's already running in production on AWS. Here's what you need to do next to start contributing.

---

## 📋 Step 1: Local Development Setup (15 minutes)

### 1.1 Verify Prerequisites

Check you have these installed:
```powershell
# Check Python version (need 3.11+)
python --version

# Check PostgreSQL
psql --version

# Check Redis
redis-cli --version

# Check Git
git --version
```

### 1.2 Set Up Virtual Environment

```powershell
cd C:\Users\KANCHAN\ai-backend

# Activate virtual environment
.\_venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 1.3 Configure Local Environment

Create a `.env` file for **local development** (separate from production):

```env
# Database - LOCAL
DB_URL=postgresql://postgres:password@localhost:5432/ai_whatsapp_dev

# Redis - LOCAL
REDIS_URI=redis://localhost:6379

# Google AI - Use development key
GOOGLE_API_KEY=your_dev_gemini_api_key

# WhatsApp - Use test account
WHATSAPP_ACCESS_TOKEN=your_test_whatsapp_token
WHATSAPP_PHONE_NUMBER_ID=your_test_phone_number_id
VERIFY_TOKEN=your_test_verify_token

# Server - LOCAL
PORT=5000
ENVIRONMENT=development
```

**⚠️ IMPORTANT**: 
- Never use production credentials locally
- Never commit `.env` file to Git (it's in `.gitignore`)
- Ask team lead for test/dev credentials

### 1.4 Set Up Local Database

```powershell
# Create local database
psql -U postgres
CREATE DATABASE ai_whatsapp_dev;
\q

# Run schema
psql -U postgres -d ai_whatsapp_dev -f db.sql
```

### 1.5 Start Local Services

**Terminal 1 - Start Redis:**
```powershell
redis-server
```

**Terminal 2 - Start FastAPI Server:**
```powershell
cd C:\Users\KANCHAN\ai-backend
.\_venv\Scripts\Activate.ps1
python run_server.py
```

**Terminal 3 - Start Celery Worker:**
```powershell
cd C:\Users\KANCHAN\ai-backend
.\_venv\Scripts\Activate.ps1
celery -A tasks worker -l info -P solo -Q default,state
```

### 1.6 Verify Local Setup

```powershell
# Check system health
.\test_celery\check_celery.ps1

# Run full test suite
.\test_celery\test_full_flow.ps1
```

Expected output:
```
✅ Server: healthy
✅ Database: connected
✅ Redis: connected
✅ Celery: 1 workers active
```

---

## 🔄 Step 2: Git Workflow

### 2.1 Understand Branch Strategy

```
main (production) ← deployed on AWS
  ↓
develop (staging)
  ↓
feature/your-feature-name (your work)
```

### 2.2 Before Starting Work

```powershell
# Update your local repository
git checkout develop
git pull origin develop

# Create feature branch
git checkout -b feature/your-feature-name

# Example:
git checkout -b feature/add-voice-message-support
```

### 2.3 During Development

```powershell
# Check status
git status

# Stage changes
git add .

# Commit with descriptive message
git commit -m "feat: add voice message processing support"

# Push to remote
git push origin feature/your-feature-name
```

### 2.4 Commit Message Convention

Follow this format:
```
<type>: <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

**Examples:**
```
feat: add operator typing indicator
fix: resolve message deduplication issue
docs: update API reference for new endpoint
refactor: optimize database queries in message_router
test: add unit tests for handback endpoint
```

---

## 🧪 Step 3: Testing Your Changes

### 3.1 Local Testing

Before pushing code, always test:

```powershell
# 1. Check system health
.\test_celery\check_celery.ps1

# 2. Run full workflow test
.\test_celery\test_full_flow.ps1

# 3. Test specific endpoints
.\test_endpoints_scripts\test_takeover.ps1
.\test_endpoints_scripts\test_operator_message.ps1
.\test_endpoints_scripts\test_handback.ps1
```

### 3.2 Manual Testing

```powershell
# Test webhook
curl -X POST http://localhost:5000/webhook `
  -H "Content-Type: application/json" `
  -d '{"entry":[{"changes":[{"value":{"messages":[{"from":"919876543210","text":{"body":"Hello"}}]}}]}]}'

# Test takeover
curl -X POST http://localhost:5000/api/v1/takeover `
  -H "Content-Type: application/json" `
  -d '{"phone":"919876543210"}'

# Check health
curl http://localhost:5000/health
```

### 3.3 Check Logs

Monitor logs for errors:
- **FastAPI logs**: Terminal 2 output
- **Celery logs**: Terminal 3 output
- **Database logs**: Check PostgreSQL logs

---

## 📝 Step 4: Code Standards

### 4.1 Python Style Guide

- Follow PEP 8
- Use type hints
- Add docstrings to functions
- Keep functions small and focused

**Example:**
```python
from typing import Optional

def process_message(phone: str, message: str) -> dict:
    """
    Process incoming message from customer.
    
    Args:
        phone: Customer phone number
        message: Message text
        
    Returns:
        dict: Processing result with status
    """
    # Implementation
    return {"status": "success"}
```

### 4.2 File Organization

```
ai-backend/
├── app.py                  # Main FastAPI app
├── bot.py                  # LangGraph AI engine
├── tasks.py                # Celery tasks
├── config.py               # Configuration
├── blueprints/             # API endpoints
│   ├── webhook.py
│   ├── takeover.py
│   └── handback.py
├── utility/                # Helper functions
│   ├── message_router.py
│   └── message_buffer.py
└── agent_tools/            # AI tools
```

### 4.3 Adding New Features

**For new API endpoint:**
1. Create file in `blueprints/`
2. Add route and handler
3. Update `app.py` to include blueprint
4. Add tests
5. Update API documentation

**For new Celery task:**
1. Add task in `tasks.py`
2. Configure queue in `celery_config.py`
3. Add error handling
4. Test task execution

**For new utility function:**
1. Create file in `utility/`
2. Add type hints and docstrings
3. Write unit tests
4. Import where needed

---

## 🚀 Step 5: Deployment Process

### 5.1 Code Review

1. Push your feature branch
2. Create Pull Request (PR) to `develop`
3. Fill PR template:
   ```markdown
   ## Description
   Brief description of changes
   
   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Breaking change
   
   ## Testing
   - [ ] Local tests passed
   - [ ] Manual testing completed
   
   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Documentation updated
   - [ ] No breaking changes
   ```
4. Wait for code review approval
5. Address review comments if any

### 5.2 Staging Deployment

After PR is merged to `develop`:
1. Changes are deployed to staging environment
2. Team tests on staging
3. Monitor for issues

### 5.3 Production Deployment (AWS)

**You don't deploy directly to production!**

Production deployment is handled by:
- Team lead or DevOps engineer
- Automated CI/CD pipeline
- After staging approval

**Production deployment steps (for reference):**
1. Merge `develop` → `main`
2. CI/CD pipeline triggers
3. Runs tests
4. Deploys to AWS
5. Runs health checks
6. Monitors for errors

---

## 🔍 Step 6: Understanding Production Setup

### 6.1 AWS Architecture

```
Internet
   ↓
AWS Application Load Balancer (HTTPS)
   ↓
EC2 Instance(s) - FastAPI + Celery
   ↓
├── RDS PostgreSQL (Database)
├── ElastiCache Redis (Cache)
└── CloudWatch (Monitoring)
```

### 6.2 Production Services

**Running as systemd services (Linux):**
- `ai-backend-api.service` - FastAPI server
- `ai-backend-celery.service` - Celery worker
- `ai-backend-flower.service` - Celery monitoring

**Configuration files:**
- `/etc/systemd/system/ai-backend-*.service`
- `/opt/ai-backend/.env` (production credentials)

### 6.3 Monitoring Production

**You can monitor (read-only):**
- CloudWatch logs
- Flower dashboard (Celery monitoring)
- Health endpoint: `https://your-domain.com/health`

**You cannot:**
- SSH into production servers (unless authorized)
- Modify production database directly
- Change production environment variables

---

## 📚 Step 7: Important Files & Documentation

### 7.1 Must-Read Documentation

| File | Purpose |
|------|---------|
| `README.md` | Project overview |
| `docs/QUICK_START.md` | Quick setup guide |
| `docs/DOCUMENTATION.md` | Complete system docs |
| `docs/API_REFERENCE.md` | API documentation |
| `docs/TESTING_GUIDE.md` | Testing procedures |
| `test_celery/celery_production.md` | Production deployment |

### 7.2 Key Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables (local) |
| `requirements.txt` | Python dependencies |
| `db.sql` | Database schema |
| `celery_config.py` | Celery configuration |
| `uvicorn_config.py` | Server configuration |

### 7.3 Understanding the Codebase

**Message Flow:**
```
WhatsApp → webhook.py → message_router.py → Celery tasks → AI/Operator
```

**Key Components:**
- `app.py` - FastAPI application entry point
- `bot.py` - LangGraph AI conversation engine
- `tasks.py` - Celery background tasks
- `message_router.py` - Routes messages to AI or operator
- `message_buffer.py` - Buffers rapid messages
- `handle_with_ai.py` - AI processing logic

---

## 🐛 Step 8: Debugging & Troubleshooting

### 8.1 Common Issues

**Issue: Database connection failed**
```powershell
# Check PostgreSQL is running
Get-Service postgresql*

# Check connection
psql -U postgres -d ai_whatsapp_dev
```

**Issue: Redis connection failed**
```powershell
# Check Redis is running
redis-cli ping
# Should return: PONG
```

**Issue: Celery not processing tasks**
```powershell
# Check Celery worker is running
# Look at Terminal 3 output

# Check Redis queue
redis-cli
> LLEN celery
> LRANGE celery 0 -1
```

**Issue: Import errors**
```powershell
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### 8.2 Debugging Tips

**Enable debug logging:**
```python
# In config.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

**Check database state:**
```sql
-- Active conversations
SELECT * FROM conversation WHERE human_intervention_required = TRUE;

-- Recent messages
SELECT * FROM message ORDER BY created_at DESC LIMIT 10;

-- Celery state
SELECT * FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 5;
```

**Monitor Celery tasks:**
```powershell
# In Redis CLI
redis-cli
> KEYS celery*
> LLEN celery
```

---

## 🤝 Step 9: Getting Help

### 9.1 Before Asking for Help

1. Check documentation
2. Search existing issues/PRs
3. Review error logs
4. Try debugging yourself

### 9.2 How to Ask for Help

**Good question format:**
```
**Problem**: Celery task failing with timeout error

**What I tried**:
1. Checked Redis connection - working
2. Checked task logs - see timeout after 30s
3. Tested locally - works fine

**Environment**:
- Branch: feature/add-voice-support
- Python: 3.11.5
- Error log: [paste error]

**Question**: Should I increase task timeout or is there a better approach?
```

### 9.3 Resources

- **Team Chat**: Ask in development channel
- **Documentation**: Check `docs/` folder
- **Code Comments**: Read inline comments
- **Git History**: `git log` to see past changes

---

## ✅ Step 10: Contributor Checklist

Before submitting PR, verify:

- [ ] Code follows project style guidelines
- [ ] All tests pass locally
- [ ] New features have tests
- [ ] Documentation updated
- [ ] Commit messages follow convention
- [ ] No sensitive data in code
- [ ] `.env` not committed
- [ ] No console.log or debug prints
- [ ] Error handling implemented
- [ ] Type hints added
- [ ] Docstrings added to functions

---

## 🎯 Quick Reference Commands

### Daily Development
```powershell
# Start development environment
.\_venv\Scripts\Activate.ps1
python run_server.py                              # Terminal 1
celery -A tasks worker -l info -P solo -Q default,state  # Terminal 2

# Check health
.\test_celery\check_celery.ps1

# Run tests
.\test_celery\test_full_flow.ps1
```

### Git Workflow
```powershell
git checkout develop
git pull origin develop
git checkout -b feature/your-feature
# ... make changes ...
git add .
git commit -m "feat: your feature description"
git push origin feature/your-feature
# ... create PR ...
```

### Testing
```powershell
# Health check
curl http://localhost:5000/health

# API docs
# Open: http://localhost:5000/docs

# Check Celery
.\test_celery\check_celery.ps1
```

---

## 🚦 Next Steps

1. ✅ Complete local setup (Step 1)
2. ✅ Read key documentation files
3. ✅ Run all tests successfully
4. ✅ Pick your first issue/task
5. ✅ Create feature branch
6. ✅ Make changes and test
7. ✅ Submit PR for review

---

## 📞 Contact

- **Team Lead**: [Contact info]
- **DevOps**: [Contact info]
- **Documentation Issues**: Create issue in repo

---

**Welcome to the team! Happy coding! 🚀**
