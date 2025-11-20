# Git Workflow Guide

## Current Branch
You're currently on: `feature/time-clock-enhancements`

## Pushing to GitHub

### Step 1: Create a GitHub Repository (if you haven't already)
1. Go to [GitHub.com](https://github.com)
2. Click the "+" icon → "New repository"
3. Name it (e.g., `cs120-food-truck`)
4. **Don't** initialize with README (since you already have files)
5. Copy the repository URL (e.g., `https://github.com/yourusername/cs120-food-truck.git`)

### Step 2: Add Remote and Push
```bash
# Add your GitHub repository as remote (replace with your actual URL)
git remote add origin https://github.com/yourusername/cs120-food-truck.git

# Push the current branch to GitHub
git push -u origin feature/time-clock-enhancements
```

### Step 3: Create Pull Request (Optional)
1. Go to your GitHub repository
2. You'll see a banner suggesting to create a pull request
3. Click "Compare & pull request"
4. Review changes and merge to `main` branch when ready

## Branch Management

### View all branches
```bash
git branch -a
```

### Switch branches
```bash
git checkout main          # Switch to main branch
git checkout feature/time-clock-enhancements  # Switch back to feature branch
```

### Merge feature branch to main
```bash
git checkout main
git merge feature/time-clock-enhancements
git push origin main
```

## Deployment Workflows

### How Changes Take Effect on Live Sites

#### 1. **Manual Deployment** (Traditional)
- Make changes locally
- Push to GitHub
- SSH into server
- Pull latest changes: `git pull origin main`
- Restart application: `sudo systemctl restart your-app`

#### 2. **Automatic Deployment** (CI/CD)
Most modern platforms auto-deploy when you push to a specific branch:

**Render.com** (if you're using it):
- Connect your GitHub repo
- Set branch to `main` (or your production branch)
- Every push to `main` triggers automatic deployment
- Changes go live in 1-5 minutes

**Heroku**:
```bash
git push heroku main  # Deploys to Heroku
```

**Vercel/Netlify**:
- Connected to GitHub
- Auto-deploys on push to `main` branch
- Preview deployments for other branches

#### 3. **Your Current Setup**
Based on your files (`Procfile`, `render.yaml`), you might be using **Render.com**:

**To deploy changes:**
1. Merge your feature branch to `main`:
   ```bash
   git checkout main
   git merge feature/time-clock-enhancements
   git push origin main
   ```

2. Render will automatically:
   - Detect the push
   - Build your application
   - Deploy to production
   - Restart services

**Deployment time:** Usually 2-5 minutes

## Best Practices

### 1. Always work on feature branches
```bash
git checkout -b feature/new-feature-name
# Make changes
git add -A
git commit -m "Description of changes"
git push origin feature/new-feature-name
```

### 2. Test before merging
- Test locally first
- Create pull request for review
- Merge to main when ready

### 3. Commit messages
Use clear, descriptive messages:
- ✅ Good: "Add time clock early checkout feature"
- ❌ Bad: "fix stuff"

## Quick Reference

```bash
# Initialize (already done)
git init

# Create and switch to new branch
git checkout -b feature/your-feature-name

# Stage all changes
git add -A

# Commit changes
git commit -m "Your commit message"

# Push to GitHub (first time)
git push -u origin branch-name

# Push subsequent changes
git push

# View changes
git status
git log --oneline

# Undo last commit (keep changes)
git reset --soft HEAD~1

# Discard local changes
git checkout -- filename
```

## Troubleshooting

### If you get "remote origin already exists"
```bash
git remote remove origin
git remote add origin YOUR_REPO_URL
```

### If you need to update remote URL
```bash
git remote set-url origin NEW_REPO_URL
```

### View current remotes
```bash
git remote -v
```

