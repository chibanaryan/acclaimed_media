---
name: deploy
description: Handle commit, push, and deployment workflows for Acclaimed Games. Use when user says "commit and push", "deploy", "push to production", or "push to heroku". Includes Tailwind build, static file collection, DEVLOG updates, and pre-commit hook handling.
---

# Deployment Skill

This skill handles the complete workflow for committing code and deploying to production.

## Trigger Words

Activate this skill when the user mentions:
- "commit and push" (without "deploy") → Commit and Push Workflow only
- "deploy", "production", or "heroku" → Complete Deployment Workflow

## Commit and Push Workflow (NO Heroku deployment)

Use this when saving changes to the repository WITHOUT deploying:

### Steps

1. **Update DEVLOG.md** (if changes warrant documentation)
   - Only for: bug fixes, features, optimizations, breaking changes
   - Keep to 8 bullet points max per day
   - Use brief, imperative language (e.g., "Fix double-load on first search")
   - Group by date with `## YYYY-MM-DD` header

2. **Build Tailwind CSS for production**
   ```bash
   python3 manage.py tailwind build
   ```

3. **Collect static files**
   ```bash
   python3 manage.py collectstatic --noinput
   ```

4. **Stage all changes**
   ```bash
   git add -A
   ```

5. **Commit with descriptive message**
   ```bash
   git commit -m "Your commit message here"
   ```

6. **Push to main branch**
   ```bash
   git push origin main
   ```

**STOP HERE** - Do NOT push to Heroku unless explicitly asked to deploy.

## Complete Deployment Workflow

Follow all steps above, then add:

7. **Deploy to Heroku**
   ```bash
   git push heroku main
   ```

## Pre-commit Hook Handling

Pre-commit hooks enforce code quality. If they fail:

| Failure Type | Action |
|--------------|--------|
| Coverage failures | Add tests or proper exclusions (not workarounds) |
| Linting failures | Fix the code to comply with standards |
| Test failures | Fix the failing tests or broken code |

**NEVER skip or work around pre-commit hooks.**

## DEVLOG Guidelines

### When to Update
- Bug fixes that resolve user-reported issues
- Performance improvements or optimizations
- New features or functionality
- Significant refactoring or architectural changes
- API or database schema modifications

### When NOT to Update
- Minor style or formatting changes
- Documentation-only updates (unless substantive)
- Test-only commits with no production changes
- Dependency version bumps without notable behavior changes

### Format Example
```markdown
## 2025-11-22
- Fixed double-load on first search character in developer list
- Added pagination to game search results
```

## Production URL

https://www.acclaimedvideogames.com/
