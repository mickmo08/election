# Billing

Entitlements (plans, quotas, features) and usage metering are implemented (`plans`, `usage_events`,
`/api/v1/admin/usage`). **No billing provider is integrated**: pricing, invoicing and payment collection need a
product decision and provider credentials. The admin UI states this explicitly and no payment is simulated.
Integration plan once decided: map plans to provider prices, create customers per tenant
(`tenants.billing_customer_ref`), push monthly usage aggregates, and handle provider webhooks idempotently.
