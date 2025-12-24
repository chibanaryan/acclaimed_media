# User Authentication Implementation Progress

## Branch
`feature/user-auth` - commit `225dcaf2`

## Overview
Implementing user authentication using django-allauth with email-only login (no username). The UI follows a modal-based pattern similar to thegreatestbooks.org.

---

## What's Been Implemented

### 1. Backend Setup
- **django-allauth** installed with socialaccount support (for future OAuth)
- Email-only authentication configured (no username field)
- Email verification disabled for now (simpler onboarding)
- ProfileView added for `/accounts/profile/`
- Context processor for newsletter subscription status

### 2. UI Components

#### Auth Modal (`_auth_modal.html`)
- Alpine.js state management with three views:
  - **Options view**: "Continue with Email" button + disabled Google placeholder
  - **Login view**: Email/password form with login/signup toggle
  - **Forgot password view**: Email input for password reset
- AJAX form submission with CSRF token
- Triggered by `.auth-modal-trigger` class

#### Profile Dropdown (Sidebar)
- DaisyUI dropdown with "Profile" button
- Options: "Edit Profile" (modal) and "Logout" (direct link)

#### Profile Modal (`_profile_modal.html`)
- Shows user email and member since date
- Newsletter subscription toggle (integrates with Subscriber model)
- "Coming Soon" section for game tracking
- Links to email management and password change pages

### 3. Templates Created

| Template | URL | Purpose | Used? |
|----------|-----|---------|-------|
| `base_auth.html` | - | Base layout for standalone auth pages | Yes |
| `login.html` | `/accounts/login/` | Standalone login page | Yes |
| `signup.html` | `/accounts/signup/` | Standalone signup page | Yes |
| `logout.html` | `/accounts/logout/` | Logout confirmation | Yes |
| `password_reset.html` | `/accounts/password/reset/` | Request password reset | Yes |
| `password_reset_done.html` | `/accounts/password/reset/done/` | "Check your email" page | Yes |
| `password_reset_from_key.html` | `/accounts/password/reset/key/<key>/` | Set new password | Yes |
| `password_reset_from_key_done.html` | `/accounts/password/reset/key/done/` | "Password changed" page | Yes |
| `password_change.html` | `/accounts/password/change/` | Change password (logged in) | Yes |
| `email.html` | `/accounts/email/` | Manage email addresses | Yes |
| `profile.html` | `/accounts/profile/` | User profile page | Yes |

**Note:** All templates ARE used. The standalone pages (`login.html`, `signup.html`) are fallbacks when JavaScript is disabled or when users navigate directly to URLs.

### 4. Templates NOT Created (allauth defaults will be used)

| Template | URL | When Used |
|----------|-----|-----------|
| `account_inactive.html` | `/accounts/inactive/` | If user account is deactivated |
| `reauthenticate.html` | `/accounts/reauthenticate/` | Sensitive action re-auth |
| `password_set.html` | `/accounts/password/set/` | Social auth users without password |
| `email_confirm.html` | `/accounts/confirm-email/<key>/` | Email verification (disabled) |

These can be created later if needed. Currently they'll show unstyled allauth defaults.

### 5. Navigation Updates
- **Sidebar**: Profile dropdown (logged in) or Login button (logged out)
- **Mobile nav**: Edit Profile / Logout links or Login link
- Auth modal and profile modal included in `base.html`

### 6. Tests
18 auth-specific tests added in `games/tests/test_auth.py`:
- Login/signup page loads
- Login with email works
- Invalid credentials error
- Logout flow
- Profile access control
- Signup creates user
- Password reset sends email
- Navigation auth links

---

## Manual Testing Checklist

### Authentication Flow (Modal)
- [ ] Click "Login" button in sidebar - modal opens
- [ ] Click "Continue with Email" - shows login form
- [ ] Toggle to "Create Account" - shows password confirmation field
- [ ] Submit signup with valid data - account created, page reloads
- [ ] Submit login with valid credentials - logged in, page reloads
- [ ] Submit login with invalid credentials - error message shown
- [ ] Click "Forgot your password?" - shows reset form
- [ ] Submit password reset - redirects to done page

### Authentication Flow (Standalone Pages)
- [ ] Navigate to `/accounts/login/` directly - login page loads
- [ ] Navigate to `/accounts/signup/` directly - signup page loads
- [ ] Complete signup on standalone page - works correctly

### Logged-In User
- [ ] Profile dropdown appears in sidebar
- [ ] Click "Edit Profile" - profile modal opens
- [ ] Newsletter toggle works (check database)
- [ ] Click "Manage Email Addresses" - email page loads
- [ ] Click "Change Password" - password change page loads
- [ ] Click "Logout" - logout confirmation page
- [ ] Confirm logout - redirected to home

### Password Reset Flow
- [ ] Request password reset with valid email
- [ ] Check email received (console backend in dev)
- [ ] Click reset link - set new password page loads
- [ ] Submit new password - success page shown
- [ ] Login with new password - works

### Mobile Navigation
- [ ] Auth links appear in hamburger menu
- [ ] Modal triggers work on mobile
- [ ] Logout link works

### Edge Cases
- [ ] Try to access `/accounts/profile/` when logged out - redirects to login
- [ ] Try to access `/accounts/password/change/` when logged out - redirects to login
- [ ] Signup with existing email - error shown
- [ ] Signup with mismatched passwords - error shown

---

## Known Issues / TODO

### Current Issues
1. **CSRF in modal**: Fixed by adding `credentials: 'same-origin'` to fetch
2. **Error handling in modal**: Generic error messages - could be more specific

### Future Enhancements
1. **Google OAuth**: Button placeholder exists, needs provider setup
2. **Email verification**: Currently disabled, enable when ready
3. **Game tracking**: "Coming Soon" placeholder in profile modal
4. **Username/display name**: Currently email-only, may want display names later

---

## Files Modified

```
acclaimedgames/settings.py      - allauth config, context processor
acclaimedgames/urls.py          - allauth URLs, profile URL
games/views.py                  - ProfileView
games/context_processors.py     - user_subscription
games/templates/base.html       - modal includes, MDI icons
games/templates/includes/_sidebar.html
games/templates/includes/_nav_mobile.html
requirements.txt                - django-allauth
```

## Files Created

```
games/templates/account/        - 11 auth templates
games/templates/includes/_auth_modal.html
games/templates/includes/_profile_modal.html
games/tests/test_auth.py
```

## Files Deleted

```
games/templates/registration/login.html  - replaced by allauth
```

---

## Configuration Reference

```python
# settings.py
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
```

---

## Next Steps

1. Complete manual testing checklist above
2. Decide on email verification strategy
3. Set up Google OAuth when ready
4. Implement game tracking feature (the main reason for user accounts)
