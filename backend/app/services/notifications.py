import logging
from app.config import settings
from twilio.rest import Client

log = logging.getLogger("sentinel.notifications")

def send_critical_alert_notification(alert_title: str, alert_summary: str, location: str):
    """Simulates sending an SMS or Webhook to an on-call duty officer.
    If Twilio credentials are provided, sends a real WhatsApp alert."""
    log.info(f"[WEBHOOK/SMS TRIGGERED] Critical Alert at {location}: {alert_title}")
    log.info(f"Details: {alert_summary}")
    
    if getattr(settings, 'TWILIO_ACCOUNT_SID', None) and getattr(settings, 'TWILIO_AUTH_TOKEN', None) and getattr(settings, 'TWILIO_WHATSAPP_TO', None):
        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = client.messages.create(
                from_=f"whatsapp:{getattr(settings, 'TWILIO_WHATSAPP_FROM', '+14155238886')}",
                body=f"🚨 *CRITICAL SENTINEL ALERT* 🚨\n\n*Threat:* {alert_title}\n*Location:* {location}\n\n*Summary:* {alert_summary}",
                to=f"whatsapp:{settings.TWILIO_WHATSAPP_TO}"
            )
            log.info(f"WhatsApp alert sent successfully. SID: {message.sid}")
        except Exception as e:
            log.error(f"Failed to send WhatsApp alert via Twilio: {e}")
