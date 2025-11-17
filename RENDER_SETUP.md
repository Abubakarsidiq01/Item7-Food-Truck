# Quick Render Deployment Checklist

## Before Deploying

✅ Code is pushed to GitHub  
✅ `Procfile` exists  
✅ `requirements.txt` includes `gunicorn`  
✅ `render.yaml` is configured (optional but recommended)  
✅ Environment variables are documented  

## Deployment Steps

### 1. Create Render Account
- Go to https://render.com
- Sign up or log in

### 2. Create New Web Service
- Click "New +" → "Web Service"
- Connect your GitHub repository
- Select the repository and branch

### 3. Configure Service
- **Name**: `item7-food-truck` (or your choice)
- **Environment**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app`
- **Python Version**: `3.11.0` (or latest)

### 4. Set Environment Variables

Add these in the "Environment" section:

**Required:**
```
SECRET_KEY=<generate a random 32+ character string>
```

**Optional:**
```
ADMIN_EMAILS=admin1@example.com,admin2@example.com
FLASK_ENV=production
```

**To generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Note:** OTP email verification is disabled. Users are automatically verified on registration. No SMTP configuration needed.

### 5. Deploy
- Click "Create Web Service"
- Wait for build to complete
- Your app will be live at: `https://your-service-name.onrender.com`

## After Deployment

1. ✅ Test registration
2. ✅ Test staff login
3. ✅ Test schedule booking
4. ✅ Check application logs for errors

## Common Issues

**Build fails:**
- Check Python version compatibility
- Verify all dependencies in requirements.txt

**App crashes:**
- Check environment variables are set
- Review logs in Render dashboard

**Note:** Email/OTP verification is not enabled. Users are auto-verified on registration.

## Need Help?

See `DEPLOYMENT.md` for detailed instructions.

