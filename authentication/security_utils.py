"""
Security utilities for TMS data scraping
"""
import ssl
import hashlib
import secrets
import logging
from typing import Dict, Optional
from cryptography.fernet import Fernet
from django.conf import settings
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class TMSSecurity:
    """Security utilities for TMS scraping"""
    
    @staticmethod
    def get_secure_headers() -> Dict[str, str]:
        """Get secure headers for HTTP requests"""
        return {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }
    
    @staticmethod
    def get_secure_browser_args() -> list:
        """Get secure browser launch arguments"""
        return [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-images',  # Faster loading
            '--disable-javascript-harmony-shipping',
            '--disable-ipc-flooding-protection',
            '--disable-renderer-backgrounding',
            '--disable-backgrounding-occluded-windows',
            '--disable-field-trial-config',
            '--disable-back-forward-cache',
            '--disable-component-extensions-with-background-pages',
            '--no-default-browser-check',
            '--no-first-run',
            '--disable-background-timer-throttling',
            '--force-dark-mode',
            '--aggressive-cache-discard',
            '--disable-background-networking',
            '--disable-sync',
            '--disable-translate',
            '--hide-scrollbars',
            '--metrics-recording-only',
            '--mute-audio',
            '--no-default-browser-check',
            '--no-first-run',
            '--disable-logging',
            '--disable-permissions-api',
            '--disable-notifications'
        ]
    
    @staticmethod
    def validate_tms_url(url: str) -> bool:
        """Validate TMS URL to prevent SSRF attacks"""
        try:
            parsed = urlparse(url)
            
            # Check if it's a valid TMS domain
            if not parsed.hostname:
                return False
                
            # Only allow nepsetms.com.np domains
            if not parsed.hostname.endswith('.nepsetms.com.np'):
                return False
                
            # Check for valid TMS server numbers (1-99)
            if 'tms' in parsed.hostname:
                server_part = parsed.hostname.split('.')[0]
                if server_part.startswith('tms'):
                    try:
                        server_num = int(server_part[3:])
                        if not (1 <= server_num <= 99):
                            return False
                    except ValueError:
                        return False
            
            # Ensure HTTPS
            if parsed.scheme != 'https':
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"URL validation error: {e}")
            return False
    
    @staticmethod
    def sanitize_input(data: str) -> str:
        """Sanitize input data to prevent injection attacks"""
        if not data:
            return ""
        
        # Remove potentially dangerous characters
        dangerous_chars = ['<', '>', '"', "'", '&', ';', '(', ')', '|', '`', '$']
        sanitized = data
        
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, '')
        
        # Limit length
        sanitized = sanitized[:100]
        
        return sanitized.strip()
    
    @staticmethod
    def generate_session_token() -> str:
        """Generate secure session token"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def hash_sensitive_data(data: str) -> str:
        """Hash sensitive data for logging purposes"""
        return hashlib.sha256(data.encode()).hexdigest()[:8]
    
    @staticmethod
    def verify_ssl_certificate(hostname: str) -> bool:
        """Verify SSL certificate of the target host"""
        try:
            import socket
            import ssl
            
            context = ssl.create_default_context()
            with socket.create_connection((hostname, 443), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    logger.info(f"SSL certificate verified for {hostname}")
                    return True
                    
        except Exception as e:
            logger.error(f"SSL verification failed for {hostname}: {e}")
            return False
    
    @staticmethod
    def create_secure_context():
        """Create secure browser context with additional protection"""
        return {
            'bypass_csp': False,
            'java_script_enabled': True,
            'accept_downloads': False,
            'ignore_https_errors': False,
            'color_scheme': 'dark',
            'reduced_motion': 'reduce',
            'forced_colors': 'none',
            'extra_http_headers': TMSSecurity.get_secure_headers()
        }

class DataProtection:
    """Data protection utilities"""
    
    @staticmethod
    def encrypt_sensitive_data(data: str, key: bytes = None) -> str:
        """Encrypt sensitive data before temporary storage"""
        if not key:
            # Generate a key - in production, this should be stored securely
            key = Fernet.generate_key()
        
        f = Fernet(key)
        encrypted_data = f.encrypt(data.encode())
        return encrypted_data.decode()
    
    @staticmethod
    def decrypt_sensitive_data(encrypted_data: str, key: bytes) -> str:
        """Decrypt sensitive data"""
        f = Fernet(key)
        decrypted_data = f.decrypt(encrypted_data.encode())
        return decrypted_data.decode()
    
    @staticmethod
    def validate_transaction_data(data: Dict) -> bool:
        """Validate transaction data integrity"""
        required_fields = ['scrip', 'units', 'buying_price', 'transaction_date']
        
        # Check required fields exist
        for field in required_fields:
            if field not in data:
                logger.warning(f"Missing required field: {field}")
                return False
        
        # Validate data types and ranges
        try:
            units = int(data['units'])
            price = float(data['buying_price'])
            
            if units <= 0 or units > 1000000:  # Reasonable limits
                logger.warning(f"Invalid units: {units}")
                return False
                
            if price <= 0 or price > 100000:  # Reasonable price limits
                logger.warning(f"Invalid price: {price}")
                return False
                
            # Validate scrip name (should be alphanumeric, 2-10 chars)
            scrip = str(data['scrip']).strip().upper()
            if not scrip.isalnum() or len(scrip) < 2 or len(scrip) > 10:
                logger.warning(f"Invalid scrip: {scrip}")
                return False
                
        except (ValueError, TypeError) as e:
            logger.warning(f"Data validation error: {e}")
            return False
        
        return True
    
    @staticmethod
    def log_security_event(event_type: str, details: str, user_id: Optional[int] = None):
        """Log security events for monitoring"""
        log_entry = {
            'timestamp': logger.time.strftime('%Y-%m-%d %H:%M:%S'),
            'event_type': event_type,
            'details': details,
            'user_id': user_id,
            'session_hash': TMSSecurity.hash_sensitive_data(str(user_id) if user_id else 'anonymous')
        }
        
        logger.info(f"SECURITY_EVENT: {log_entry}")
