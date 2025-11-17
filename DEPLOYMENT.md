# Deployment Guide for Item7 Food Truck on Render

This guide will help you deploy the Item7 Food Truck application on Render.

## Prerequisites

1. A Render account (sign up at https://render.com)
2. A GitHub repository with your code (or use Render's Git integration)
3. Gmail App Password for email sending (if using email verification)

## Step 1: Prepare Your Repository

Make sure your code is pushed to GitHub or another Git repository that Render can access.

## Step 2: Create a New Web Service on Render

1. Log in to your Render dashboard
2. Click "New +" and select "Web Service"
3. Connect your GitHub repository (or provide your repository URL)
4. Render will auto-detect the settings from `render.yaml` if present

## Step 3: Configure Build Settings

Render should auto-detect these from `render.yaml`:
- **Name**: item7-food-truck (or your preferred name)
- **Environment**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app`

## Step 4: Set Environment Variables

In the Render dashboard, go to your service's "Environment" tab and add these variables:

### Required Variables:

1. **SECRET_KEY**
   - Generate a strong random secret key
   - You can use: `python -c "import secrets; print(secrets.token_hex(32))"`
   - Or let Render generate it (it's set to `generateValue: true` in render.yaml)

2. **SMTP_SERVER**
   - For Gmail: `smtp.gmail.com`
   - For other providers, use their SMTP server

3. **SMTP_PORT**
   - For Gmail: `587`
   - Already set in render.yaml

4. **SMTP_USERNAME**
   - Your Gmail address (e.g., `your-email@gmail.com`)

5. **SMTP_PASSWORD**
   - Your Gmail App Password (not your regular password)
   - Generate one at: https://myaccount.google.com/apppasswords

6. **FROM_EMAIL**
   - Usually the same as SMTP_USERNAME
   - The email address that sends verification emails

7. **ADMIN_EMAILS** (Optional)
   - Comma-separated list of admin email addresses
   - Example: `admin1@example.com,admin2@example.com`

### Optional Variables:

- **FLASK_ENV**: Set to `production` for production mode
- **PORT**: Automatically set by Render (don't override)

## Step 5: Deploy

1. Click "Create Web Service" or "Save Changes"
2. Render will start building and deploying your application
3. Monitor the build logs for any errors
4. Once deployed, your app will be available at: `https://your-service-name.onrender.com`

## Step 6: Verify Deployment

1. Visit your deployed URL
2. Test registration and email verification
3. Test staff login and schedule booking
4. Check that CSV files are being created in the `data/` directory

## Important Notes

### Data Persistence

- CSV files are stored in the `data/` directory
- On Render, this directory persists between deployments
- However, if you delete the service, all data will be lost
- For production, consider using a database (PostgreSQL) instead of CSV files

### Email Configuration

- Make sure your Gmail App Password is correct
- Check that "Less secure app access" is enabled (if required by your Gmail account)
- Test email sending after deployment

### Security

- Never commit `.env` file to Git
- Use strong SECRET_KEY in production
- Consider enabling HTTPS (Render provides this automatically)
- Review and update ADMIN_EMAILS as needed

## Troubleshooting

### Build Fails

- Check that `requirements.txt` is correct
- Verify Python version compatibility
- Check build logs for specific errors

### App Crashes on Start

- Check that all environment variables are set
- Verify `gunicorn` is installed (included in requirements.txt)
- Check application logs in Render dashboard

### Email Not Sending

- Verify SMTP credentials are correct
- Check that App Password is valid (not regular password)
- Review application logs for SMTP errors
- Test SMTP connection using the test script

### Data Not Persisting

- Ensure `data/` directory exists and is writable
- Check file permissions
- Review application logs for file I/O errors

## Updating Your Deployment

1. Push changes to your Git repository
2. Render will automatically detect changes and redeploy
3. Monitor the deployment logs

## Support

For issues specific to:
- **Render**: Check Render documentation or support
- **Application**: Review application logs in Render dashboard
- **Email**: Verify SMTP settings and credentials

