# DreamCart

DreamCart combines the two supplied ecommerce projects into a single Flask shop. It includes a responsive catalogue, customer accounts, persistent cart and wishlist, product reviews, coupons, checkout, order tracking, contact-message storage, and a protected store admin.

## Start locally

Requires Python 3.10 or newer.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open http://127.0.0.1:5000. DreamCart uses SQLite and creates `instance/shop.db` on first run. The included merged database is preloaded with the combined catalogue and anonymized demo history. If you want a completely empty local database, stop the app, remove `instance/shop.db`, then start it again.

## Demo admin

- Email: `admin@dreamcart.com`
- Password: `Change123!`

Change the admin password and `SECRET_KEY` in `.env` before sharing the site. Since the bundled database is pre-seeded, apply a changed admin password with `flask --app app reset-admin-password`. Customer accounts can be created from **Sign in → Create an account**.

## Payment and email setup

Cash on delivery works without extra services. Optional Stripe Checkout runs in test mode when `STRIPE_SECRET_KEY` is set in `.env` and the Stripe package is installed. Checkout sends the customer to Stripe; DreamCart verifies the paid session on the server before saving an order. Raw card numbers are never stored by DreamCart. Stripe is configured for card payments in this project.

Password reset links are emailed only when SMTP values (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`) are set in `.env`. Reset links expire after one hour. The contact form saves messages for admins to review at `/admin/messages`; it does not send email.

## Included data from both archives

The merged SQLite database contains 9 combined categories, 16 deduplicated products, the `WELCOME10` and `DEMO` coupons, and 4 example orders with a review and wishlist item. Source admin accounts were not imported. Demo order history and the review are attached to a generated **Sample Shopper** account with a random inaccessible password; source delivery addresses were replaced with a generic demo address.

## Store and admin pages

- Store: `/`, `/products`, `/product/<slug>`
- Customer: `/register`, `/login`, `/account`, `/cart`, `/wishlist`, `/checkout`
- Orders: `/orders/<number>`
- Admin: `/admin`, with product, category, order, customer, review, coupon and contact-message management

## Project structure

```text
app.py                  Flask routes, authentication, checkout, admin tools
config.py               Environment-based settings
models.py               SQLAlchemy database models
requirements.txt        Flask, Flask-SQLAlchemy and optional Stripe SDK
templates/              Storefront, customer and admin Jinja pages
static/css/style.css    Responsive DreamCart visual design
static/js/main.js       Small interaction helpers
static/uploads/         Validated admin image uploads
instance/shop.db        Merged SQLite catalog and demo data
```

The database supports users, categories, products, cart and wishlist items, orders, order items, payments, reviews, coupons and contact messages. Passwords are hashed, forms use session CSRF tokens, admin routes require an admin account, and image uploads are limited to 5 MB and checked against PNG/JPG/WebP file signatures.
