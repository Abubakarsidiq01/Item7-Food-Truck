# Stripe Payment Setup Guide

## Quick Setup (For Testing)

To enable Stripe card payments, you need to get test API keys from Stripe.

### Step 1: Get Stripe Test Keys

1. Go to [Stripe Dashboard](https://dashboard.stripe.com/test/apikeys)
2. Sign up for a free account (or log in if you have one)
3. Make sure you're in **Test mode** (toggle in the top right)
4. Copy your **Publishable key** (starts with `pk_test_...`)
5. Click "Reveal test key" to get your **Secret key** (starts with `sk_test_...`)

### Step 2: Add Keys to Your Environment

**Option A: Create a `.env` file** (Recommended)

Create a `.env` file in the project root:

```bash
STRIPE_SECRET_KEY=sk_test_your_actual_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_actual_publishable_key_here
```

**Option B: Set environment variables**

```bash
export STRIPE_SECRET_KEY="sk_test_your_actual_secret_key_here"
export STRIPE_PUBLISHABLE_KEY="pk_test_your_actual_publishable_key_here"
```

### Step 3: Restart the Server

After adding the keys, restart your Flask server:

```bash
python3 app.py
```

### Step 4: Test with Stripe Test Card

When testing payments, use Stripe's test card:
- **Card Number:** `4242 4242 4242 4242`
- **Expiry:** Any future date (e.g., 12/25)
- **CVC:** Any 3 digits (e.g., 123)
- **ZIP:** Any 5 digits (e.g., 12345)

## Current Status

- ✅ **Cash on Delivery** - Always available (no setup needed)
- ⚠️ **Card Payment** - Requires Stripe keys to be configured

If Stripe is not configured, the card payment option will be disabled and you'll only see "Cash on Delivery" as an option.

## Troubleshooting

**Error: "Invalid API Key provided"**
- Make sure you copied the keys correctly (no extra spaces)
- Ensure you're using **test keys** (start with `pk_test_` and `sk_test_`)
- Restart the server after adding keys

**Card payment option not showing**
- Check that both `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY` are set
- Make sure the keys don't start with `pk_test_51QEXAMPLE` or `sk_test_51QEXAMPLE` (those are placeholders)

## Production

For production, you'll need to:
1. Switch to **Live mode** in Stripe dashboard
2. Get your **live keys** (start with `pk_live_` and `sk_live_`)
3. Update your environment variables
4. Use HTTPS (required for Stripe in production)

