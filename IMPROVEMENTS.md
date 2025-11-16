# Improvement Checklist

## Critical (Do First)
- [ ] Move Sentry DSN to environment variable
- [ ] Fix SQL injection in utils.py:66 (use sql.SQL and sql.Identifier)
- [ ] Remove debug print() statement in utils.py:181
- [ ] Run `npm audit fix` to fix frontend vulnerabilities
- [ ] Add basic API tests using pytest-django

## High Priority
- [ ] Add error handling for IGDB API calls
- [ ] Add retry logic for IGDB requests (use tenacity library)
- [ ] Add rate limiting for IGDB API
- [ ] Add proper logging configuration
- [ ] Refactor global year_rankings/decade_rankings to use cache

## Medium Priority
- [ ] Add type hints to all functions
- [ ] Add docstrings explaining parameters and file formats
- [ ] Add API documentation using drf-spectacular
- [ ] Add frontend component tests using Vitest
- [ ] Consider TypeScript for frontend type safety

## Nice to Have
- [ ] Set up CI/CD with GitHub Actions
- [ ] Add pre-commit hooks for linting
- [ ] Improve Heroku deployment (use buildpacks instead of committing dist/)
- [ ] Add .editorconfig for consistent formatting
- [ ] Add code coverage reporting

## Quick Wins (< 30 minutes each)
1. Move SENTRY_DSN to .env
2. Remove print() statement
3. Run npm audit fix
4. Add __str__ docstrings to utility functions
5. Add basic logging config
