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

```
SECRET_KEY=<generate a random 32+ character string>
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-gmail-app-password
FROM_EMAIL=your-email@gmail.com
ADMIN_EMAILS=admin1@example.com,admin2@example.com
FLASK_ENV=production
```

**To generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**To get Gmail App Password:**
1. Go to https://myaccount.google.com/apppasswords
2. Generate a new app password for "Mail"
3. Use the 16-character password (no spaces)

### 5. Deploy
- Click "Create Web Service"
- Wait for build to complete
- Your app will be live at: `https://your-service-name.onrender.com`

## After Deployment

1. ✅ Test registration
2. ✅ Test email verification
3. ✅ Test staff login
4. ✅ Test schedule booking
5. ✅ Check application logs for errors

## Common Issues

**Build fails:**
- Check Python version compatibility
- Verify all dependencies in requirements.txt

**App crashes:**
- Check environment variables are set
- Review logs in Render dashboard

**Email not working:**
- Verify Gmail App Password (not regular password)
- Check SMTP settings are correct

## Need Help?

See `DEPLOYMENT.md` for detailed instructions.

