"""
Transactional Email Notifications via Resend API (https://resend.com).

Uses the already-installed `requests` library to call `POST https://api.resend.com/emails`.
If `RESEND_API_KEY` is not configured, calls log a warning and return False without crashing
checkout, admin updates, or contact submissions.
"""
import logging
import requests
from django.conf import settings
from django.utils.html import escape

logger = logging.getLogger(__name__)
RESEND_API_URL = 'https://api.resend.com/emails'


def send_resend_email(to_email, subject, html_body, text_body=None, reply_to=None):
    """Send a single email via Resend REST API. Returns True on 2xx, False otherwise."""
    api_key = getattr(settings, 'RESEND_API_KEY', '').strip()
    from_email = getattr(settings, 'RESEND_FROM_EMAIL', 'MAPSCART <onboarding@resend.dev>').strip()

    if not api_key:
        logger.warning("RESEND_API_KEY not configured; skipping email '%s' to %s", subject, to_email)
        return False
    if not to_email:
        return False

    recipients = [to_email] if isinstance(to_email, str) else [e for e in to_email if e]
    if not recipients:
        return False

    payload = {
        'from': from_email,
        'to': recipients,
        'subject': subject,
        'html': html_body,
    }
    if text_body:
        payload['text'] = text_body
    if reply_to:
        payload['reply_to'] = reply_to

    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=8,
        )
        if 200 <= resp.status_code < 300:
            logger.info("Resend email sent: '%s' -> %s", subject, recipients)
            return True
        logger.warning("Resend API error (%s) for '%s': %s", resp.status_code, subject, resp.text[:300])
        return False
    except Exception as exc:
        logger.warning("Resend request failed for '%s': %s", subject, exc)
        return False


def _wrap_html(title, preheader, body_html):
    site_url = getattr(settings, 'SITE_BASE_URL', 'https://mapscart.com').rstrip('/')
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#F5F8FC;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#132639;">
  <div style="display:none;max-height:0;overflow:hidden;">{escape(preheader)}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#F5F8FC;padding:28px 12px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;width:100%;background:#FFFFFF;border:1px solid #D1DEE8;border-radius:18px;overflow:hidden;">
        <tr>
          <td style="background:#1F3A66;padding:24px 28px;text-align:center;">
            <div style="font-size:22px;font-weight:800;letter-spacing:1.5px;color:#FFFFFF;">MAPSCART</div>
            <div style="font-size:12px;color:#B3E0FF;margin-top:4px;">Handcrafted Anti-Tarnish Jewellery &bull; Curated in Delhi</div>
          </td>
        </tr>
        <tr>
          <td style="padding:28px;">
            <h1 style="margin:0 0 14px;font-size:22px;color:#132639;">{escape(title)}</h1>
            {body_html}
          </td>
        </tr>
        <tr>
          <td style="background:#F8FAFC;border-top:1px solid #E1E9F0;padding:18px 28px;text-align:center;font-size:12px;color:#52637A;">
            Need help? Reply to this email or visit <a href="{site_url}/contact/" style="color:#1F3A66;font-weight:600;">MAPSCART Support</a> &bull;
            <a href="{site_url}/my-orders/" style="color:#1F3A66;font-weight:600;">My Orders</a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _order_items_table(order):
    rows = []
    for item in order.items.select_related('product').all():
        title = escape(item.product.title)
        color = f" <span style='color:#52637A;'>({escape(item.color)})</span>" if item.color else ""
        free = " <span style='background:#DCFCE7;color:#166534;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;'>FREE</span>" if item.is_free_gift else ""
        price_str = "&#8377;0" if item.is_free_gift else f"&#8377;{item.price}"
        rows.append(
            f"<tr>"
            f"<td style='padding:10px 0;border-bottom:1px solid #E1E9F0;font-size:14px;'>{item.quantity} &times; {title}{color}{free}</td>"
            f"<td align='right' style='padding:10px 0;border-bottom:1px solid #E1E9F0;font-size:14px;font-weight:600;'>{price_str}</td>"
            f"</tr>"
        )
    discount_row = ""
    if getattr(order, 'discount_amount', 0):
        discount_row = (
            f"<tr><td style='padding:10px 0;border-bottom:1px solid #E1E9F0;color:#166534;font-size:14px;'>Offer Savings</td>"
            f"<td align='right' style='padding:10px 0;border-bottom:1px solid #E1E9F0;color:#166534;font-weight:700;'>-&#8377;{order.discount_amount}</td></tr>"
        )
    return (
        "<table width='100%' cellspacing='0' cellpadding='0' style='margin:16px 0;border-top:1px solid #E1E9F0;'>"
        + "".join(rows)
        + discount_row
        + f"<tr><td style='padding:12px 0;font-size:16px;font-weight:800;'>Total</td>"
          f"<td align='right' style='padding:12px 0;font-size:16px;font-weight:800;'>&#8377;{order.amount_paid}</td></tr>"
          "</table>"
    )


def send_order_placed_email(order):
    """Notify customer (and optional admin) right after an order is placed."""
    site_url = getattr(settings, 'SITE_BASE_URL', 'https://mapscart.com').rstrip('/')
    pay_url = f"{site_url}/order/{order.id}/pay/"
    body = f"""
        <p style="font-size:15px;line-height:1.65;margin:0 0 14px;">
            Hi <strong>{escape(order.full_name)}</strong>, thank you for placing Order ID <strong>{order.id}</strong> with MAPSCART!
        </p>
        <p style="font-size:14.5px;line-height:1.65;margin:0 0 14px;color:#2B3F57;">
            Please complete your UPI / Paytm QR payment of <strong>&#8377;{order.amount_paid}</strong> and upload your payment screenshot if you haven't already.
        </p>
        {_order_items_table(order)}
        <div style="background:#F8FAFC;border:1px solid #E1E9F0;border-radius:12px;padding:14px 16px;font-size:13.5px;color:#2B3F57;margin-bottom:20px;">
            <strong>Delivery Address:</strong><br>
            {escape(order.full_name)}<br>
            {escape(order.shipping_address)}, {escape(order.city)} - {escape(order.postal_code)}<br>
            Phone: {escape(order.mobile_number)}
        </div>
        <div style="text-align:center;">
            <a href="{pay_url}" style="display:inline-block;background:#1F3A66;color:#FFFFFF;text-decoration:none;font-weight:700;font-size:14px;padding:12px 26px;border-radius:999px;">
                View Order &amp; Complete Payment
            </a>
        </div>
    """
    html = _wrap_html(
        f"Order ID {order.id} Placed — MAPSCART",
        f"Your MAPSCART Order ID {order.id} for Rs.{order.amount_paid} has been placed.",
        body,
    )
    send_resend_email(order.email, f"MAPSCART Order ID {order.id} Placed (₹{order.amount_paid})", html)

    admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', '').strip()
    if admin_email:
        send_resend_email(
            admin_email,
            f"[MAPSCART Admin] New Order ID {order.id} — ₹{order.amount_paid} ({order.full_name})",
            html,
        )


def send_payment_submitted_email(order):
    """Notify customer (and optional admin) when a payment screenshot is uploaded."""
    site_url = getattr(settings, 'SITE_BASE_URL', 'https://mapscart.com').rstrip('/')
    body = f"""
        <p style="font-size:15px;line-height:1.65;margin:0 0 14px;">
            Hi <strong>{escape(order.full_name)}</strong>, we received your payment screenshot for Order ID <strong>{order.id}</strong> (<strong>&#8377;{order.amount_paid}</strong>).
        </p>
        <p style="font-size:14.5px;line-height:1.65;margin:0 0 20px;color:#2B3F57;">
            Our team is verifying your payment now. You will receive an order confirmation email as soon as it is verified.
        </p>
        <div style="text-align:center;">
            <a href="{site_url}/my-orders/" style="display:inline-block;background:#1F3A66;color:#FFFFFF;text-decoration:none;font-weight:700;font-size:14px;padding:12px 26px;border-radius:999px;">
                Track Order Status
            </a>
        </div>
    """
    html = _wrap_html(
        f"Payment Screenshot Received — Order ID {order.id}",
        f"We received your payment screenshot for Order ID {order.id}.",
        body,
    )
    send_resend_email(order.email, f"Payment Screenshot Received — MAPSCART Order ID {order.id}", html)

    admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', '').strip()
    if admin_email:
        send_resend_email(
            admin_email,
            f"[MAPSCART Admin] Payment Screenshot Uploaded — Order ID {order.id}",
            html,
        )


def send_order_confirmed_email(order):
    """Notify customer when admin marks payment verified (`is_paid=True`)."""
    site_url = getattr(settings, 'SITE_BASE_URL', 'https://mapscart.com').rstrip('/')
    body = f"""
        <div style="background:#DCFCE7;color:#166534;padding:12px 16px;border-radius:12px;font-weight:700;font-size:14px;margin-bottom:18px;">
            &#10004; Payment Verified &amp; Order Confirmed!
        </div>
        <p style="font-size:15px;line-height:1.65;margin:0 0 14px;">
            Hi <strong>{escape(order.full_name)}</strong>, great news! Your payment of <strong>&#8377;{order.amount_paid}</strong> for Order ID <strong>{order.id}</strong> is verified and your order is now <strong>confirmed</strong>.
        </p>
        {_order_items_table(order)}
        <p style="font-size:14px;color:#2B3F57;margin:0 0 20px;">
            We are carefully inspecting and packing your jewellery. You will receive another update once it ships!
        </p>
        <div style="text-align:center;">
            <a href="{site_url}/my-orders/" style="display:inline-block;background:#1F3A66;color:#FFFFFF;text-decoration:none;font-weight:700;font-size:14px;padding:12px 26px;border-radius:999px;">
                View My Orders
            </a>
        </div>
    """
    html = _wrap_html(
        f"Order Confirmed! — Order ID {order.id}",
        f"Your MAPSCART Order ID {order.id} is confirmed!",
        body,
    )
    send_resend_email(order.email, f"Order Confirmed! MAPSCART Order ID {order.id}", html)


def send_order_status_email(order):
    """Notify customer when order status changes (PROCESSING, SHIPPED, DELIVERED, CANCELLED)."""
    site_url = getattr(settings, 'SITE_BASE_URL', 'https://mapscart.com').rstrip('/')
    status_copy = {
        'PROCESSING': ("Your Order is Being Prepared", "Our atelier team is inspecting and gift-packing your jewellery."),
        'SHIPPED': ("Your Order Has Shipped!", "Your MAPSCART parcel is on its way to you."),
        'DELIVERED': ("Your Order Has Been Delivered", "Your MAPSCART order has been delivered. We hope you love wearing it!"),
        'CANCELLED': ("Order Cancelled", "Your order has been cancelled. If you have any questions, please reach out to us."),
    }
    headline, desc = status_copy.get(
        order.status,
        (f"Order Status Updated: {order.get_status_display()}", f"Your Order ID {order.id} status is now {order.get_status_display()}."),
    )
    tracking_html = ""
    if order.tracking_number:
        tracking_html = (
            f"<div style='background:#EFF6FF;border:1px solid #BFDBFE;border-radius:12px;padding:12px 16px;margin:14px 0;font-size:14px;color:#1E3A8A;'>"
            f"<strong>Tracking Number:</strong> {escape(order.tracking_number)}</div>"
        )
    body = f"""
        <p style="font-size:15px;line-height:1.65;margin:0 0 12px;">
            Hi <strong>{escape(order.full_name)}</strong>, here is an update on your Order ID <strong>{order.id}</strong>:
        </p>
        <p style="font-size:14.5px;line-height:1.65;margin:0 0 14px;color:#2B3F57;">{escape(desc)}</p>
        {tracking_html}
        <div style="text-align:center;margin-top:20px;">
            <a href="{site_url}/my-orders/" style="display:inline-block;background:#1F3A66;color:#FFFFFF;text-decoration:none;font-weight:700;font-size:14px;padding:12px 26px;border-radius:999px;">
                View Order Details
            </a>
        </div>
    """
    html = _wrap_html(f"{headline} — Order ID {order.id}", headline, body)
    send_resend_email(order.email, f"{headline} (MAPSCART Order ID {order.id})", html)


def send_contact_inquiry_email(inquiry):
    """Send confirmation to customer and alert admin when a contact inquiry is submitted."""
    if inquiry.email:
        body = f"""
            <p style="font-size:15px;line-height:1.65;margin:0 0 14px;">
                Hi <strong>{escape(inquiry.name)}</strong>, thank you for contacting MAPSCART!
            </p>
            <p style="font-size:14.5px;line-height:1.65;margin:0 0 14px;color:#2B3F57;">
                We have received your message regarding <strong>{escape(inquiry.subject)}</strong> and our team will reply shortly.
            </p>
            <div style="background:#F8FAFC;border:1px solid #E1E9F0;border-radius:12px;padding:14px 16px;font-size:13.5px;color:#2B3F57;">
                <strong>Your Message:</strong><br>{escape(inquiry.message)}
            </div>
        """
        html = _wrap_html("We Received Your Message", "Thank you for contacting MAPSCART.", body)
        send_resend_email(inquiry.email, f"We received your message — MAPSCART ({inquiry.subject})", html)

    admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', '').strip()
    if admin_email:
        admin_body = f"""
            <p style="font-size:14.5px;line-height:1.65;">
                <strong>From:</strong> {escape(inquiry.name)} ({escape(inquiry.email or 'no email')}, {escape(inquiry.phone or 'no phone')})<br>
                <strong>Subject:</strong> {escape(inquiry.subject)}
            </p>
            <div style="background:#F8FAFC;border:1px solid #E1E9F0;border-radius:12px;padding:14px 16px;font-size:14px;">
                {escape(inquiry.message)}
            </div>
        """
        admin_html = _wrap_html("New Contact Inquiry", f"Inquiry from {inquiry.name}", admin_body)
        send_resend_email(
            admin_email,
            f"[MAPSCART Inquiry] {inquiry.subject} — {inquiry.name}",
            admin_html,
            reply_to=inquiry.email or None,
        )
