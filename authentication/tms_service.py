
import asyncio
import re
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

# Add logger instance
logger = logging.getLogger(__name__)


try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("Playwright not available. Install it with: pip install playwright && playwright install")
    PLAYWRIGHT_AVAILABLE = False
    
from django.contrib.auth.models import User
from django.db import IntegrityError
from asgiref.sync import sync_to_async
from .models import Share_Buy


class TMSDataFetcher:
    """
    Service class to automate data fetching from TMS Nepse website
    Uses manual login approach to handle captcha
    Supports automated fetching with stored credentials
    """

    def __init__(self, tms_number: int = 52, settlement_type: str = "PaymentDue"):
        self.tms_number = tms_number
        self.settlement_type = settlement_type  
        self.base_url = f"https://tms{tms_number}.nepsetms.com.np"
        self.login_url = f"{self.base_url}/tms/login"
        self.settlement_url = f"{self.base_url}/tms/me/gen-bank/settlement-buy-info#{self.settlement_type}"
        self.valid_stocks = None
        

    async def fetch_with_stored_credentials(self, user: User = None) -> Dict:
        """
        Fetch TMS data using stored credentials (automated approach)
        """
        try:
            # Get TMS configuration
            config = await self.get_active_tms_config()
            if not config:
                return {
                    'success': False,
                    'error': 'No active TMS configuration found. Please set up TMS credentials first.',
                    'records_found': 0,
                    'records_saved': 0
                }
            
            if not config.tms_username or not config.tms_password:
                return {
                    'success': False,
                    'error': 'TMS credentials not configured. Please set username and password.',
                    'records_found': 0,
                    'records_saved': 0
                }
            
            logger.info(f"Using stored TMS credentials for automated fetch...")
            
            # Load valid stocks for validation
            await self.get_valid_stocks()
            
            # Use existing fetch method but with automated login
            return await self.fetch_and_save_data_automated(
                username=config.tms_username,
                password=config.tms_password,
                user=user
            )
            
        except Exception as e:
            logger.error(f"Error in automated fetch: {e}")
            return {
                'success': False,
                'error': f'Automated fetch failed: {str(e)}',
                'records_found': 0,
                'records_saved': 0
            }
        
    async def wait_for_manual_login(self, page):
        """
        Wait for user to manually login through the browser
        """
        try:
            logger.info(f"Opening TMS login page: {self.login_url}")
            await page.goto(self.login_url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            
            try:
                logger.info("Login page ready ")
            except:
                pass
            
            logger.info("Waiting for user to complete manual login...")
            logger.info("Please fill in your username, password, and captcha, then click login...")
            
            logger.info("Now monitoring for login completion...")
            
            success_indicators = [
                'a:has-text("Logout")',
                'button:has-text("Logout")', 
                '.logout',
                'a:has-text("logout")',
                '[href*="logout"]',
                '.user-menu',
                '.dashboard',
                'text="Welcome"',
                '.welcome'
            ]
            
            login_success = False
            for attempt in range(60): 
                try:
                    current_url = page.url
                    logger.info(f"Checking login status... Current URL: {current_url}")
                    
                    if "/login" not in current_url.lower() and self.base_url in current_url:
                        login_success = True
                        logger.info(f"Login success detected: redirected away from login page to {current_url}")
                        break
                    
                    for indicator in success_indicators:
                        try:
                            element = await page.query_selector(indicator)
                            if element:
                                login_success = True
                                logger.info(f"Login success detected with element: {indicator}")
                                break
                        except:
                            continue
                    
                    if login_success:
                        break
                    
                    # Third check: Look for absence of login form (but only if URL changed)
                    if "/login" not in current_url.lower():
                        try:
                            login_form = await page.query_selector('input[name="username"], input[type="password"], input[name="password"]')
                            if not login_form:
                                login_success = True
                                logger.info("Login success detected: login form not present and URL changed")
                                break
                        except:
                            pass
                    
                    await asyncio.sleep(5)  
                    
                except Exception as e:
                    logger.warning(f"Error checking login status: {e}")
                    await asyncio.sleep(5)
            
            if login_success:
                logger.info("Manual login completed successfully")
                return True
            else:
                raise Exception("Login timeout - user did not complete login within 5 minutes")
                
        except Exception as e:
            logger.error(f"Manual login failed: {str(e)}")
            raise Exception(f"Manual login failed: {str(e)}")

    async def fetch_settlement_data(self, page):
        """
        Fetch settlement data from the payment due section with enhanced parsing for TMS structure
        """
        try:
            # First verify the page is still accessible
            try:
                current_url = page.url
                logger.info(f"Starting settlement data fetch. Current URL: {current_url}")
            except Exception as e:
                raise Exception(f"Page is not accessible: {e}")
            
            logger.info(f"Navigating to settlement page: {self.settlement_url}")
            
            # Navigate with better error handling
            try:
                await page.goto(self.settlement_url, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                logger.error(f"Failed to navigate to settlement page: {e}")
                # Try alternative approach - maybe we're already on the right domain
                current_url = page.url
                if self.base_url in current_url:
                    logger.info("Already on TMS domain, trying to navigate via JS")
                    await page.evaluate(f'window.location.href = "{self.settlement_url}"')
                    await page.wait_for_load_state("networkidle", timeout=30000)
                else:
                    raise Exception(f"Cannot navigate to settlement page: {e}")
            
            # Wait for content to load
            await asyncio.sleep(5)
            settlement_data = []
            business_date = None
            
            # First, try to extract business date from the main table
            try:
                # Look for business date in the main table rows (format: 2025-03-30)
                main_table_rows = await page.query_selector_all('table tr')
                for row in main_table_rows[:15]:  # Check first several rows for business date
                    cells = await row.query_selector_all('td')
                    if len(cells) >= 3:
                        for cell in cells:
                            text = await cell.text_content()
                            if text and text.strip():
                                # Look for date in YYYY-MM-DD format
                                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text.strip())
                                if date_match:
                                    try:
                                        business_date = datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
                                        logger.info(f"Found business date: {business_date}")
                                        break
                                    except:
                                        pass
                    if business_date:
                        break
                        
                # If not found, also check for business date text
                if not business_date:
                    page_content = await page.content()
                    date_patterns = [
                        r'BUSINESS DATE[:\s]*(\d{4}-\d{2}-\d{2})',
                        r'Business Date[:\s]*(\d{4}-\d{2}-\d{2})',
                        r'(\d{4}-\d{2}-\d{2})'
                    ]
                    for pattern in date_patterns:
                        match = re.search(pattern, page_content)
                        if match:
                            try:
                                business_date = datetime.strptime(match.group(1), '%Y-%m-%d').date()
                                logger.info(f"Found business date from content: {business_date}")
                                break
                            except:
                                pass
                        if business_date:
                            break
                            
            except Exception as e:
                logger.warning(f"Could not extract business date: {e}")
                # Use current date as fallback
                business_date = datetime.now().date()
                logger.info(f"Using current date as fallback: {business_date}")
            
            # Try to expand all detail rows first
            await self.expand_detail_rows(page)
            
            # Look for detail rows (expanded transaction details)
            detail_rows = await page.query_selector_all('tr.k-detail-row')
            logger.info(f"Found {len(detail_rows)} detail rows")
            
            for detail_row in detail_rows:
                try:
                    # Look for the nested transaction detail table within this detail row
                    nested_tables = await detail_row.query_selector_all('table')
                    
                    for table in nested_tables:
                        # Check if this table has the transaction detail columns we expect
                        header_row = await table.query_selector('thead tr')
                        if header_row:
                            headers = await header_row.query_selector_all('th')
                            header_texts = []
                            for header in headers:
                                text = await header.text_content()
                                header_texts.append(text.strip() if text else "")
                            
                            # Check if this looks like the transaction detail table
                            if any('STOCK SYMBOL' in h for h in header_texts) and any('RATE' in h for h in header_texts):
                                logger.info(f"Found transaction detail table with headers: {header_texts}")
                                
                                # Process data rows
                                data_rows = await table.query_selector_all('tbody tr')
                                for row in data_rows:
                                    cells = await row.query_selector_all('td')
                                    if len(cells) >= 6:  # Ensure we have enough columns
                                        cell_texts = []
                                        for cell in cells:
                                            text = await cell.text_content()
                                            cell_texts.append(text.strip() if text else "")
                                        
                                        logger.info(f"Transaction row: {cell_texts}")
                                        scrip_data = self.parse_settlement_row(cell_texts)
                                        if scrip_data:
                                            # Use business date if we found it
                                            if business_date:
                                                scrip_data['transaction_date'] = business_date
                                            settlement_data.append(scrip_data)
                                            logger.info(f"Added parsed data: {scrip_data}")
                
                except Exception as e:
                    logger.error(f"Error processing detail row: {e}")
                    continue
            
            # Fallback: if no detail rows found, try all tables
            if not settlement_data:
                logger.info("No data from detail rows, trying all tables")
                all_tables = await page.query_selector_all('table')
                logger.info(f"Found {len(all_tables)} tables total")
                
                for i, table in enumerate(all_tables):
                    try:
                        logger.info(f"Processing table {i+1}")
                        rows = await table.query_selector_all('tbody tr')
                        
                        for j, row in enumerate(rows):
                            cells = await row.query_selector_all('td')
                            if len(cells) >= 6:  # Need at least 6 columns for TMS structure
                                cell_texts = []
                                for cell in cells:
                                    text = await cell.text_content()
                                    cell_texts.append(text.strip() if text else "")
                                
                                # Skip rows that are clearly not transaction data
                                if not any(text.isalpha() and len(text) >= 3 for text in cell_texts[1:4]):
                                    continue
                                
                                logger.info(f"Table {i+1}, Row {j+1}: {cell_texts}")
                                scrip_data = self.parse_settlement_row(cell_texts)
                                if scrip_data:
                                    if business_date:
                                        scrip_data['transaction_date'] = business_date
                                    settlement_data.append(scrip_data)
                                    logger.info(f"Added parsed data: {scrip_data}")
                    
                    except Exception as e:
                        logger.error(f"Error processing table {i+1}: {e}")
                        continue
            
            logger.info(f"Total settlement data found: {len(settlement_data)}")
            return settlement_data
            
        except Exception as e:
            logger.error(f"Failed to fetch settlement data: {str(e)}")
            raise Exception(f"Failed to fetch settlement data: {str(e)}")
    
    async def expand_detail_rows(self, page):
        """
        Expand all detail rows to show transaction details
        """
        try:
            # Look for expansion buttons (plus icons)
            expansion_buttons = await page.query_selector_all('.k-icon.k-plus, .k-icon.k-minus, .k-hierarchy-cell a')
            logger.info(f"Found {len(expansion_buttons)} potential expansion buttons")
            
            for i, button in enumerate(expansion_buttons):
                try:
                    # Check if it's a plus icon (collapsed row)
                    class_name = await button.get_attribute('class')
                    if 'k-plus' in class_name or 'k-icon' in class_name:
                        logger.info(f"Clicking expansion button {i+1}")
                        await button.click()
                        await asyncio.sleep(1)  # Wait for expansion
                except Exception as e:
                    logger.warning(f"Could not click expansion button {i+1}: {e}")
                    continue
            
            # Wait for all expansions to complete
            await asyncio.sleep(3)
            
        except Exception as e:
            logger.warning(f"Error expanding detail rows: {e}")
            # Continue anyway - not critical
    
    def parse_settlement_row(self, cell_texts: List[str]) -> Optional[Dict]:
        """
        Parse a row of settlement data to extract scrip info based on TMS transaction detail structure
        Expected columns: S.N, TRANSACTION NO, STOCK SYMBOL, RATE (NPR), QUANTITY, AMOUNT (NPR), etc.
        """
        try:
            logger.info(f"Parsing row with {len(cell_texts)} cells: {cell_texts}")
            
            # Based on the TMS transaction detail structure, we expect specific column positions
            if len(cell_texts) < 6:
                logger.info("Not enough columns for TMS transaction detail structure")
                return None
            
            scrip_name = None
            rate = None
            units = None
            
            # Column mapping based on TMS transaction detail structure:
            # 0: S.N
            # 1: TRANSACTION NO  
            # 2: STOCK SYMBOL - this is the scrip name
            # 3: RATE (NPR) - this is our buying price
            # 4: QUANTITY - this is units
            # 5: AMOUNT (NPR) - this is total amount
            
            try:
                # Extract STOCK SYMBOL (column 2)
                if len(cell_texts) > 2:
                    symbol_text = cell_texts[2].strip()
                    # Check if this looks like a valid stock symbol (3-8 uppercase letters)
                    if symbol_text and len(symbol_text) >= 2 and symbol_text.replace('.', '').isalpha():
                        scrip_name = symbol_text.upper()
                        logger.info(f"Found stock symbol: {scrip_name}")
                
                # Extract RATE (column 3) - buying price
                if len(cell_texts) > 3:
                    rate_text = cell_texts[3].strip()
                    # Remove commas and spaces, keep decimal points
                    rate_clean = re.sub(r'[,\s]', '', rate_text)
                    if rate_clean and re.match(r'^\d+(\.\d+)?$', rate_clean):
                        rate = Decimal(rate_clean)
                        logger.info(f"Found rate: {rate}")
                
                # Extract QUANTITY (column 4) - units
                if len(cell_texts) > 4:
                    quantity_text = cell_texts[4].strip()
                    # Remove commas and spaces
                    quantity_clean = re.sub(r'[,\s]', '', quantity_text)
                    if quantity_clean and quantity_clean.isdigit():
                        units = int(quantity_clean)
                        logger.info(f"Found quantity: {units}")
                
                logger.info(f"Extracted: scrip={scrip_name}, rate={rate}, units={units}")
                
                # Validate that we have the essential data
                if scrip_name and rate and units and units > 0 and rate > 0:
                    return {
                        'scrip': scrip_name,
                        'units': units,
                        'buying_price': rate,
                        'transaction_date': datetime.now().date()  # Will be updated with business date
                    }
                else:
                    logger.info(f"Missing required data or invalid values: scrip={scrip_name}, rate={rate}, units={units}")
                
            except Exception as e:
                logger.error(f"Error extracting specific columns: {e}")
                # Try fallback parsing
                return self.parse_settlement_row_fallback(cell_texts)
            
            return None
            
        except Exception as e:
            logger.error(f"Error parsing row: {e}")
            return None
    
    def parse_settlement_row_fallback(self, cell_texts: List[str]) -> Optional[Dict]:
        """
        Fallback parsing method using pattern matching
        """
        try:
            scrip_name = None
            buying_price = None
            units = None
            total_amount = None
            
            # Enhanced patterns for fallback parsing
            scrip_patterns = [
                r'\b[A-Z]{3,8}\b',  # 3-8 uppercase letters
                r'\b[A-Z]+[0-9]*\b'  # Uppercase letters possibly followed by numbers
            ]
            
            for i, cell_text in enumerate(cell_texts):
                cell_text = cell_text.strip()
                logger.info(f"Cell {i}: '{cell_text}'")
                
                # Look for scrip name
                if not scrip_name:
                    for pattern in scrip_patterns:
                        matches = re.findall(pattern, cell_text)
                        for match in matches:
                            if 3 <= len(match) <= 8 and match.isalpha():
                                scrip_name = match
                                logger.info(f"Found scrip: {scrip_name}")
                                break
                
                # Look for numeric values
                if re.search(r'[\d,]+\.?\d*', cell_text):
                    # Clean the number
                    clean_number = re.sub(r'[,\s]', '', cell_text)
                    try:
                        number = float(clean_number)
                        
                        # Heuristic based on typical ranges:
                        # Rate: usually 10-10000
                        # Quantity: usually 1-10000  
                        # Amount: usually > 1000
                        
                        if 10 <= number <= 10000 and not buying_price:
                            buying_price = Decimal(str(number))
                            logger.info(f"Found potential buying price: {buying_price}")
                        elif 1 <= number <= 10000 and not units:
                            units = int(number)
                            logger.info(f"Found potential units: {units}")
                        elif number > 1000 and not total_amount:
                            total_amount = Decimal(str(number))
                            logger.info(f"Found potential total amount: {total_amount}")
                    except:
                        pass
            
            # Validate and return
            if scrip_name and buying_price and units and units > 0:
                if not total_amount:
                    total_amount = buying_price * Decimal(str(units))
                
                logger.info(f"Successfully parsed: {scrip_name}, {units} units @ {buying_price}")
                return {
                    'scrip': scrip_name,
                    'units': units,
                    'buying_price': buying_price,
                    'total_amount': total_amount,
                    'transaction_date': datetime.now().date()
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in fallback parsing: {e}")
            return None
    
    def parse_page_content(self, content: str) -> List[Dict]:
        """
        Parse entire page content as fallback method
        """
        settlement_data = []
        
        # This is a simplified version - you might need to enhance this
        # based on the actual HTML structure of the TMS pages
        
        return settlement_data
    
    async def fetch_and_save_data(self, user: User) -> Dict:
        """
        Main method to fetch data and save to database using manual login
        """
        if not PLAYWRIGHT_AVAILABLE:
            return {
                'success': False,
                'error': 'Playwright is not installed. Please run: pip install playwright && playwright install',
                'records_found': 0,
                'records_saved': 0
            }
        
        browser = None
        page = None
        
        try:
            async with async_playwright() as p:
                logger.info("Launching browser for TMS data fetch...")
                browser = await p.chromium.launch(
                    headless=False,  # Keep browser visible for manual login
                    args=[
                        '--no-sandbox', 
                        '--disable-dev-shm-usage',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security'
                    ]
                )
                
                # Create browser context and page
                context = await browser.new_context()
                page = await context.new_page()
                
                # Wait for manual login
                logger.info("Starting manual login process...")
                login_success = await self.wait_for_manual_login(page)
                if not login_success:
                    raise Exception("Manual login failed or timed out")
                
                # Add a delay and verify page is still valid
                logger.info("Login successful! Preparing to fetch settlement data...")
                await asyncio.sleep(3)
                
                # Verify page is still accessible
                try:
                    current_url = page.url
                    logger.info(f"Page verification: Current URL is {current_url}")
                    
                    # Test page responsiveness
                    title = await page.title()
                    logger.info(f"Page title: {title}")
                    
                except Exception as e:
                    logger.error(f"Page became inaccessible after login: {e}")
                    raise Exception(f"Browser page became inaccessible after login: {e}")
                
                # Fetch settlement data
                logger.info("Fetching settlement data...")
                settlement_data = await self.fetch_settlement_data(page)
                
                # Save to database
                saved_records = []
                for data in settlement_data:
                    try:
                        # Check if this record already exists
                        existing = await sync_to_async(Share_Buy.objects.filter(
                            user=user,
                            scrip=data['scrip'],
                            units=data['units'],
                            buying_price=data['buying_price'],
                            transaction_date=data['transaction_date']
                        ).first)()
                        
                        if not existing:
                            share_buy = await sync_to_async(Share_Buy.objects.create)(
                                user=user,
                                scrip=data['scrip'],
                                units=data['units'],
                                buying_price=data['buying_price'],
                                transaction_date=data['transaction_date']
                            )
                            saved_records.append(share_buy)
                            logger.info(f"Saved: {share_buy}")
                        else:
                            logger.info(f"Duplicate record skipped: {data}")
                        
                    except Exception as e:
                        logger.error(f"Error saving record {data}: {e}")
                
                logger.info(f"Data fetch completed. Found {len(settlement_data)} records, saved {len(saved_records)} new records.")
                
                # Keep browser open briefly to show results
                await asyncio.sleep(5)
                
                return {
                    'success': True,
                    'records_found': len(settlement_data),
                    'records_saved': len(saved_records),
                    'data': saved_records
                }
                
        except Exception as e:
            logger.error(f"Error in fetch_and_save_data: {e}")
            return {
                'success': False,
                'error': str(e),
                'records_found': 0,
                'records_saved': 0
            }
        
        finally:
            # Clean up browser resources
            try:
                if page:
                    await page.close()
                if browser:
                    await browser.close()
                logger.info("Browser closed successfully")
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")


# Synchronous wrapper for Django views
def fetch_tms_data(user: User, username: str = None, password: str = None, tms_number: int = None, settlement_type: str = "Due") -> Dict:
    """
    Synchronous wrapper for the async TMS data fetcher
    Uses manual login approach - username and password are not needed
    settlement_type: 'Success' or 'Due'
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            'success': False,
            'error': 'Playwright is not installed. Please run: pip install playwright && playwright install',
            'records_found': 0,
            'records_saved': 0
        }

    # Use profile settings for TMS server if not provided
    try:
        profile = user.profile_ver
        if not tms_number:
            tms_number = profile.tms_server_number
    except:
        pass

    # Fallback default
    if not tms_number:
        tms_number = 52

    fetcher = TMSDataFetcher(tms_number, settlement_type)

    # Run the async function
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(fetcher.fetch_and_save_data(user))
async def fetch_successful_purchases(self, page):
    """
    Fetch successful stock purchases from the settlement success section
    """
    try:
        # Navigate to the success page if not already there
        success_url = f"{self.base_url}/tms/me/gen-bank/settlement-buy-info#Success"
        current_url = page.url
        
        if "#Success" not in current_url:
            logger.info(f"Navigating to success page: {success_url}")
            await page.goto(success_url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(3)  # Additional wait for content to load
        
        # Wait for the main grid to load
        await page.wait_for_selector(".k-grid-table", timeout=30000)
        
        # First extract business dates from the main table
        business_dates = await self.extract_business_dates(page)
        logger.info(f"Found business dates: {business_dates}")
        
        # Expand all detail rows to show transaction details
        await self.expand_all_detail_rows(page)
        
        # Extract transaction details
        successful_purchases = []
        detail_rows = await page.query_selector_all('tr.k-detail-row')
        logger.info(f"Found {len(detail_rows)} detail rows for successful purchases")
        
        for i, detail_row in enumerate(detail_rows):
            try:
                # Get the parent row to find the business date
                parent_row_index = await detail_row.evaluate('el => el.getAttribute("data-kendo-grid-item-index")')
                business_date = business_dates.get(int(parent_row_index)) if parent_row_index else None
                
                # Find the transaction details table within this detail row
                transaction_table = await detail_row.query_selector('table.k-grid-table')
                if not transaction_table:
                    continue
                
                # Process each transaction row
                transaction_rows = await transaction_table.query_selector_all('tbody tr:not(.k-grouping-row)')
                for row in transaction_rows:
                    cells = await row.query_selector_all('td')
                    if len(cells) >= 6:  # Ensure we have enough columns
                        cell_texts = [await cell.text_content() for cell in cells]
                        cell_texts = [text.strip() if text else "" for text in cell_texts]
                        
                        # Parse the transaction data
                        transaction_data = self.parse_transaction_row(cell_texts)
                        if transaction_data:
                            if business_date:
                                transaction_data['business_date'] = business_date
                            successful_purchases.append(transaction_data)
                            logger.info(f"Added successful purchase: {transaction_data}")
            
            except Exception as e:
                logger.error(f"Error processing detail row {i}: {e}")
                continue
        
        logger.info(f"Total successful purchases found: {len(successful_purchases)}")
        return successful_purchases
    
    except Exception as e:
        logger.error(f"Failed to fetch successful purchases: {str(e)}")
        raise Exception(f"Failed to fetch successful purchases: {str(e)}")

async def extract_business_dates(self, page):
    """
    Extract business dates from the main table rows
    """
    business_dates = {}
    try:
        main_rows = await page.query_selector_all('.k-master-row')
        for i, row in enumerate(main_rows):
            try:
                cells = await row.query_selector_all('td[aria-colindex="3"]')  # Business date column
                if cells:
                    date_text = await cells[0].text_content()
                    if date_text:
                        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text.strip())
                        if date_match:
                            try:
                                business_date = datetime.strptime(date_match.group(1), '%Y-%m-%d').date()
                                business_dates[i] = business_date
                                logger.info(f"Row {i} business date: {business_date}")
                            except:
                                pass
            except:
                continue
    except Exception as e:
        logger.warning(f"Error extracting business dates: {e}")
    
    return business_dates

async def expand_all_detail_rows(self, page):
    """
    Expand all detail rows in the success table
    """
    try:
        # Find all expand buttons (plus icons)
        expand_buttons = await page.query_selector_all('.k-hierarchy-cell .k-plus')
        logger.info(f"Found {len(expand_buttons)} expand buttons")
        
        for button in expand_buttons:
            try:
                # Check if the row is not already expanded
                class_name = await button.get_attribute('class')
                if 'k-plus' in class_name:
                    await button.click()
                    await asyncio.sleep(1)  # Brief pause between clicks
            except Exception as e:
                logger.warning(f"Could not click expand button: {e}")
                continue
        
        await asyncio.sleep(2)  # Wait for all expansions to complete
    except Exception as e:
        logger.warning(f"Error expanding detail rows: {e}")

def parse_transaction_row(self, cell_texts: List[str]) -> Optional[Dict]:
    """
    Parse a row of transaction data from the success table
    Expected columns: S.N, Transaction No, Stock Symbol, Rate, Quantity, Amount, etc.
    """
    try:
        if len(cell_texts) < 6:
            return None
        
        # Column mapping for successful purchases table:
        # 0: S.N
        # 1: Transaction No
        # 2: Stock Symbol (scrip)
        # 3: Rate (buying price)
        # 4: Quantity (units)
        # 5: Amount (total)
        
        scrip = None
        rate = None
        units = None
        amount = None
        
        # Extract scrip (column 2)
        if len(cell_texts) > 2:
            scrip_text = cell_texts[2].strip().upper()
            if 2 <= len(scrip_text) <= 8 and scrip_text.isalpha():
                scrip = scrip_text
        
        # Extract rate (column 3)
        if len(cell_texts) > 3:
            rate_text = re.sub(r'[^\d.]', '', cell_texts[3])
            try:
                rate = Decimal(rate_text) if rate_text else None
            except:
                pass
        
        # Extract units (column 4)
        if len(cell_texts) > 4:
            units_text = re.sub(r'[^\d]', '', cell_texts[4])
            try:
                units = int(units_text) if units_text else None
            except:
                pass
        
        # Extract amount (column 5)
        if len(cell_texts) > 5:
            amount_text = re.sub(r'[^\d.]', '', cell_texts[5])
            try:
                amount = Decimal(amount_text) if amount_text else None
            except:
                pass
        
        # Validate required fields
        if not all([scrip, rate, units]):
            return None
        
        # Calculate amount if not provided
        if not amount:
            try:
                amount = Decimal(str(rate)) * Decimal(str(units))
            except:
                amount = None
        
        return {
            'scrip': scrip,
            'units': units,
            'buying_price': rate,
            'total_amount': amount,
            'status': 'SETTLED'
        }
    
    except Exception as e:
        logger.error(f"Error parsing transaction row: {e}")
        return None

async def fetch_and_save_successful_purchases(self, user: User) -> Dict:
    """
    Main method to fetch successful purchases and save to database
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            'success': False,
            'error': 'Playwright is not installed.',
            'records_found': 0,
            'records_saved': 0
        }
    
    browser = None
    page = None
    
    try:
        async with async_playwright() as p:
            logger.info("Launching browser for successful purchases fetch...")
            browser = await p.chromium.launch(
                headless=False,  # Visible for manual login
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            
            context = await browser.new_context()
            page = await context.new_page()
            
            # Wait for manual login
            logger.info("Starting manual login process...")
            login_success = await self.wait_for_manual_login(page)
            if not login_success:
                raise Exception("Manual login failed")
            
            logger.info("Login successful! Fetching successful purchases...")
            await asyncio.sleep(3)
            
            # Fetch successful purchases data
            purchases = await self.fetch_successful_purchases(page)
            
            # Save to database
            saved_records = []
            for purchase in purchases:
                try:
                    # Check for existing record
                    existing = await sync_to_async(Share_Buy.objects.filter(
                        user=user,
                        scrip=purchase['scrip'],
                        units=purchase['units'],
                        buying_price=purchase['buying_price'],
                        transaction_date=purchase.get('business_date')
                    ).first)()
                    
                    if not existing:
                        share_buy = await sync_to_async(Share_Buy.objects.create)(
                            user=user,
                            scrip=purchase['scrip'],
                            units=purchase['units'],
                            buying_price=purchase['buying_price'],
                            total_amount=purchase.get('total_amount'),
                            transaction_date=purchase.get('business_date'),
                            status='SETTLED'  # Or whatever status field you use
                        )
                        saved_records.append(share_buy)
                        logger.info(f"Saved successful purchase: {share_buy}")
                    else:
                        logger.info(f"Duplicate purchase skipped: {purchase}")
                
                except Exception as e:
                    logger.error(f"Error saving purchase {purchase}: {e}")
            
            logger.info(f"Found {len(purchases)} successful purchases, saved {len(saved_records)} new records")
            
            return {
                'success': True,
                'records_found': len(purchases),
                'records_saved': len(saved_records),
                'data': saved_records
            }
    
    except Exception as e:
        logger.error(f"Error in successful purchases fetch: {e}")
        return {
            'success': False,
            'error': str(e),
            'records_found': 0,
            'records_saved': 0
        }
    
    finally:
        try:
            if page:
                await page.close()
            if browser:
                await browser.close()
        except:
            pass

# Synchronous wrapper for Django
def fetch_successful_purchases_sync(user: User, tms_number: int = None) -> Dict:
    """
    Synchronous wrapper for fetching successful purchases
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            'success': False,
            'error': 'Playwright not available',
            'records_found': 0,
            'records_saved': 0
        }
    
    # Determine TMS server number
    try:
        profile = user.profile_ver
        if not tms_number:
            tms_number = profile.tms_server_number
    except:
        pass
    
    if not tms_number:
        tms_number = 52  # Default
    
    fetcher = TMSDataFetcher(tms_number)
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(fetcher.fetch_and_save_successful_purchases(user))