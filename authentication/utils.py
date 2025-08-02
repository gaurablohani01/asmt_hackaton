from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from datetime import datetime

def email_send_token(email, token):
    try:
        subject = 'Email verification - NEPSE Portfolio'
        verification_link = f"{getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')}/verify/{token}/"
        html_content = render_to_string(
            'email_verification_email.html',
            {
                'verification_link': verification_link,
                'year': datetime.now().year,
            }
        )
        email_from = getattr(settings, 'DEFAULT_FROM_EMAIL', settings.EMAIL_HOST_USER)
        reception_list = [email]
        msg = EmailMultiAlternatives(subject, '', email_from, reception_list)
        msg.attach_alternative(html_content, "text/html")
        msg.send()
    except Exception as e:
        return False
    return True


