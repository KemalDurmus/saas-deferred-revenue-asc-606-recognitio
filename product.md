# Ertelenmiş Gelir Planlayıcı — product facts

## What it does
- Calculates monthly recognized revenue and deferred revenue tables from Stripe or Paddle payment CSV exports.
- Inputs: CSV file upload (up to 5 MB / 20,000 rows), direct text paste, or built-in demo data.
- Configurable inputs: Report month (YYYY-MM) and default subscription period in months (1–60) when interval is missing.
- Processing logic: Distributes each invoice evenly by day across its service period; rounds monthly cumulative amounts to the nearest cent while ensuring the total matches the invoice amount. Filters out non-successful, zero, or negative amount rows.
- Outputs: A 24-month financial schedule (11 past months, 1 report month, 12 future months) showing opening deferred revenue, billed amounts, recognized revenue, and closing deferred revenue, broken down by currency.
- Export: Generates downloadable CSV files for the calculated tables per currency.
- Interface language: Turkish.

## What it does NOT do (never claim these)
- No external integrations or API connections (Stripe/Paddle must be manually exported as CSV).
- No automation or recurring jobs.
- No real-time data synchronization.
- No AI or machine learning features.
- No user accounts, authentication, login, or databases.
- No server-side storage of uploaded CSV data (processed in memory).
- No financial forecasting or prediction of future sales/renewals (only calculates based on existing uploaded invoices).

## Pricing and offer
- There is no paid plan, subscription, pricing page, or payment gateway in the code.

## Good fit
A SaaS founder or accountant who needs to quickly paste or upload a payment CSV export to generate a 24-month deferred revenue and recognized revenue schedule without manual spreadsheet formulas.
