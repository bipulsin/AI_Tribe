# Policy payment and issuance

After a quotation is selected, the chat shows an inline **payment card**. Payment is simulated. No Razorpay, Stripe, UPI, or card-network call is made.

## UI

The card is a structured Alpine message (`payload.kind = payment_card`) inside the WhatsApp-style thread.

- Header: selected insurer, premium (INR), **Simulated Payment — Not Real Processing**
- Methods: Google Pay, PhonePe, Paytm, Cards (generic tiles, not brand logos)
- Wallets: “Tap to open [method] on your device”
- Cards: holder name, number (asterisks except last four), expiry MM/YY, CVV
- **Pay Now** (`#00a884`). Validation: a method must be selected; card fields must be non-empty. No Luhn check.
- Disclaimer: simulated, no real charge

State lives on `policyChat()` (`selectedPayment`, card fields). `POST /policy/payment/process` sends JSON. The thread is replaced from `serialize_booking`, same as other chat steps.

## Backend

1. Verify the booking is `quote_selected` / `initiate_payment` (or retry after `payment_confirmed` if PDF generation failed).
2. Store a `policy_payments` row. Full card numbers and CVV are never stored (last four digits only; CVV as `XXX`).
3. Set status `payment_confirmed`, then generate the PDF via `app/services/policy_document.py` (ReportLab).
4. Append: green “Payment Successful! Policy issuance in process.”, a download link (`/policy/document/{policy_id}`, `target=_blank`, filename `Policy_{reference}.pdf`), and a completion message.
5. Booking status becomes `issued_demo`; step `policy_issued`.

If PDF generation fails, status stays `payment_confirmed` so Pay Now can retry. CRM list/detail show the payment method, timestamp, and policy artefact.

## Testing

1. Select a quote — payment card appears with insurer and premium.
2. Click each method — highlight + wallet prompt or card fields.
3. Pay Now with no method — in-card error.
4. Pay Now with a method — success card, download link, completion message.
5. Open the PDF: watermark **NOT A VALID INSURANCE DOCUMENT**, customer/vehicle/quote fields, disclaimer footer.
6. `/policy/crm` shows `payment_confirmed` then `issued_demo`.
7. Start a second booking from **New booking** — no leftover payment state.
