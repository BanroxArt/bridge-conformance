# Sources

Primary sources only. Checked on 2026-11-16.

- Standard Webhooks specification: signed content `msg_id.timestamp.payload`; the id stays the same across retries and the attempt timestamp changes; the timestamp tolerance check against replay; the suggestion to use `webhook-id` as an idempotency key ("save the IDs in redis for 5 minutes"); the example retry schedule to 75 hours 35 minutes; 2xx as success: https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md
- Stripe, Receive Stripe events in your webhook endpoint: "Webhook endpoints might occasionally receive the same event more than once"; "Stripe doesn't guarantee the delivery of events in the order that they're generated"; track event IDs to identify duplicates: https://docs.stripe.com/webhooks

## Not used as a source

Blog posts about webhook reliability. The harness takes its rules from what senders document, and its lifecycles are labelled as models.
