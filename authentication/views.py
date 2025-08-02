
from django.contrib.auth import authenticate, login as auth_login, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import render, redirect, HttpResponse, get_object_or_404
from .forms import UserRegistrationForm, UserLoginForm
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from authentication.models import Profile_ver, Share_Buy, Share_Sell
from authentication.utils import email_send_token
import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            messages.success(request, 'Registration successful. You can now log in.')
            return redirect('login')
    else:
        form = UserRegistrationForm()
    return render(request, 'register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()


def index(request):
    if request.user.is_authenticated:
        from decimal import Decimal
        from django.db.models import Sum
        from collections import OrderedDict

        user_purchases = Share_Buy.objects.filter(user=request.user)
        user_sales = Share_Sell.objects.filter(user=request.user)
        current_holdings_data = {}
        sold_holdings_data = {}

        for purchase in user_purchases:
            scrip = purchase.scrip
            if scrip not in current_holdings_data:
                current_holdings_data[scrip] = {
                    'scrip': scrip,
                    'total_units': 0,
                    'remaining_units': 0,
                    'total_investment': Decimal('0'),
                    'wacc': Decimal('0'),
                    'transactions': []
                }
            costs = purchase.calculate_costs()
            current_holdings_data[scrip]['total_units'] += purchase.units
            current_holdings_data[scrip]['remaining_units'] += purchase.remaining_units
            current_holdings_data[scrip]['total_investment'] += costs['total_amount']
            current_holdings_data[scrip]['transactions'].append(purchase)

        for scrip, data in current_holdings_data.items():
            if data['total_units'] > 0:
                data['wacc'] = data['total_investment'] / data['total_units']

        for sale in user_sales:
            scrip = sale.share.scrip
            if scrip not in sold_holdings_data:
                sold_holdings_data[scrip] = {
                    'scrip': scrip,
                    'total_sold_units': 0,
                    'total_cost': Decimal('0'),
                    'total_sale_value': Decimal('0'),
                    'total_tax': Decimal('0'),
                    'realized_pnl': Decimal('0'),
                    'transactions': []
                }
            profit_loss = sale.calculate_profit_loss()
            sold_holdings_data[scrip]['total_sold_units'] += sale.units_sold
            sold_holdings_data[scrip]['total_cost'] += profit_loss['total_buy_cost']
            sold_holdings_data[scrip]['total_sale_value'] += profit_loss['gross_sale']
            sold_holdings_data[scrip]['total_tax'] += profit_loss['tax_amount']
            sold_holdings_data[scrip]['realized_pnl'] += profit_loss['final_profit']
            sold_holdings_data[scrip]['transactions'].append(sale)

        all_holdings = []
        for scrip, data in current_holdings_data.items():
            current_price = data['wacc'] * Decimal('1.08') if data['wacc'] > 0 else Decimal('0')
            price_change = current_price - data['wacc'] if data['wacc'] > 0 else Decimal('0')
            percentage_change = (price_change / data['wacc'] * 100) if data['wacc'] > 0 else 0
            current_value = current_price * data['remaining_units']
            current_investment = data['wacc'] * data['remaining_units']
            unrealized_pnl = current_value - current_investment
            sold_data = sold_holdings_data.get(scrip, {})
            holding_data = {
                'scrip': scrip,
                'total_units': data['total_units'],
                'remaining_units': data['remaining_units'],
                'wacc': data['wacc'],
                'total_investment': data['total_investment'],
                'current_value': current_value,
                'current_price': current_price,
                'price_change': price_change,
                'percentage_change': percentage_change,
                'unrealized_gain': unrealized_pnl,
                'current_investment': current_investment,
                'transactions': data['transactions'],
                'sold_units': sold_data.get('total_sold_units', 0),
                'realized_pnl': sold_data.get('realized_pnl', Decimal('0')),
                'sold_transactions': sold_data.get('transactions', [])
            }
            all_holdings.append(holding_data)
        for scrip, data in sold_holdings_data.items():
            if scrip not in current_holdings_data:
                avg_selling_price = data['total_sale_value'] / data['total_sold_units'] if data['total_sold_units'] > 0 else Decimal('0')
                avg_wacc = data['total_cost'] / data['total_sold_units'] if data['total_sold_units'] > 0 else Decimal('0')
                holding_data = {
                    'scrip': scrip,
                    'total_units': data['total_sold_units'],
                    'remaining_units': 0,
                    'wacc': avg_wacc,
                    'total_investment': data['total_cost'],
                    'current_value': Decimal('0'),
                    'current_price': avg_selling_price,
                    'price_change': Decimal('0'),
                    'percentage_change': 0,
                    'unrealized_gain': Decimal('0'),
                    'current_investment': Decimal('0'),
                    'transactions': [],
                    'sold_units': data['total_sold_units'],
                    'realized_pnl': data['realized_pnl'],
                    'sold_transactions': data['transactions']
                }
                all_holdings.append(holding_data)

        # The rest of the dashboard context
        total_purchases = Share_Buy.objects.filter(user=request.user).count()
        total_sales = Share_Sell.objects.filter(user=request.user).values('transaction_group').distinct().count()
        total_holdings_count = Share_Buy.objects.filter(user=request.user, remaining_units__gt=0).values('scrip').distinct().count()
        total_invested = sum(h['total_investment'] for h in all_holdings)
        total_units = sum(h['total_units'] for h in all_holdings)

        from .nepse_api_utils import fetch_nepse_stocks_and_ltp
        nepse_stocks = fetch_nepse_stocks_and_ltp()
        nepse_ltp_map = {stock['symbol']: stock['ltp'] for stock in nepse_stocks}

        top_holdings_raw = [
            {
                'scrip': scrip,
                'units': data['remaining_units'],
                'invested_value': data['wacc'] * data['remaining_units'],
                'wacc': data['wacc'],
            }
            for scrip, data in current_holdings_data.items() if data['remaining_units'] > 0
        ]
        
        # Add LTP data
        for h in top_holdings_raw:
            h['ltp'] = nepse_ltp_map.get(h['scrip'], None)
            h['current_value'] = h['ltp'] * h['units'] if h['ltp'] else h['invested_value']
        
        # Sort by current value (LTP * units if available, otherwise invested value)
        top_holdings_raw = sorted(top_holdings_raw, key=lambda x: x['current_value'], reverse=True)[:5]
        top_holdings = top_holdings_raw

        recent_buys = Share_Buy.objects.filter(user=request.user).order_by('-transaction_date', '-id')[:10]
        recent_sells_raw = Share_Sell.objects.filter(user=request.user).order_by('-transaction_date', '-id')
        grouped_sells = OrderedDict()
        for sell in recent_sells_raw:
            group_key = sell.transaction_group if sell.transaction_group else f"{sell.transaction_date}_{sell.selling_price}"
            if group_key not in grouped_sells:
                grouped_sells[group_key] = sell
        recent_sells = list(grouped_sells.values())[:10]
        recent_activities = []
        for buy in recent_buys:
            recent_activities.append({
                'type': 'buy',
                'scrip': buy.scrip,
                'units': buy.units,
                'price': float(buy.buying_price),
                'date': buy.transaction_date,
                'action': 'Bought',
                'datetime': buy.transaction_date,
                'id': buy.id  # Add ID for consistent sorting
            })
        for sell in recent_sells:
            recent_activities.append({
                'type': 'sell',
                'scrip': sell.share.scrip,
                'units': sell.units_sold,
                'price': float(sell.selling_price),
                'date': sell.transaction_date,
                'action': 'Sold',
                'datetime': sell.transaction_date,
                'id': sell.id  # Add ID for consistent sorting
            })
        # Sort by date (newest first), then by ID (newest first) for consistent ordering
        recent_activities = sorted(recent_activities, key=lambda x: (x['datetime'], x['id']), reverse=True)[:6]

        market_status = {
            'status': 'CLOSED',
            'message': 'Market is closed',
            'next_session': 'Tomorrow at 11:00 AM'
        }

        context = {
            'total_purchases': total_purchases,
            'total_sales': total_sales,
            'total_holdings_count': total_holdings_count,
            'total_invested': total_invested,
            'total_units': total_units,
            'top_holdings': top_holdings,
            'recent_activities': recent_activities,
            'market_status': market_status,
            'available_shares': total_holdings_count,
            'all_holdings': all_holdings,
        }
        return render(request, 'dashboard.html', context)
    else:
        return render(request, 'home.html')

def register_view(request):
    if request.method == "POST":
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        
        tms_server_number = request.POST.get('tms_server_number', '52')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match!')
            return render(request, 'register.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists!')
            return render(request, 'register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered!')
            return render(request, 'register.html')

        try:
            user = User.objects.create(username=username, email=email)
            user.first_name = first_name
            user.last_name = last_name
            user.set_password(password)
            user.save()

            profile_ver = Profile_ver.objects.create(
                user=user, 
                uid=str(uuid.uuid4()),
                tms_server_number=int(tms_server_number)
            )
            email_send_token(email, profile_ver.uid)
            
            messages.success(request, 'Registration successful! Please check your email to verify your account.')
            return redirect('login')
        except Exception as e:
            messages.error(request, f'Registration failed: {e}')
            return render(request, 'register.html')
    
    return render(request, 'register.html')

def verify(request, token):
    try:
        obj1 = Profile_ver.objects.get(uid=token)
        obj1.is_verified = True
        obj1.save()
        return render(request, 'email_verified.html')
    except Profile_ver.DoesNotExist:
        return render(request, 'email_verified.html', { 'error': 'Invalid verification token.' })
    except Exception as e:
        return render(request, 'email_verified.html', { 'error': f'Error: {e}' })


def login_view(request):
    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            try:
                profile_ver = Profile_ver.objects.filter(user=user).first()
            except Exception as e:
                # Handle database schema mismatch temporarily
                print(f"Database schema error: {e}")
                profile_ver = None
                
            if profile_ver and profile_ver.is_verified:
                login(request, user)
                messages.success(request, f'Welcome back, {user.first_name or user.username}!')
                return redirect('home')
            else:
                from uuid import uuid4
                try:
                    email_to_show = user.email
                    if profile_ver:
                        new_uid = str(uuid4())
                        profile_ver.uid = new_uid
                        profile_ver.save()
                        email_send_token(email_to_show, new_uid)
                    else:
                        new_profile_ver = Profile_ver.objects.create(user=user, uid=str(uuid4()))
                        email_send_token(email_to_show, new_profile_ver.uid)
                    if email_to_show:
                        messages.warning(request, f"Your email is not verified. We've sent a new verification email to {email_to_show}. Please check your inbox and verify your account.")
                    else:
                        messages.warning(request, "Your email is not verified. We've sent a new verification email. Please check your inbox and verify your account.")
                except Exception as e:
                    messages.error(request, f"Please verify your email before logging in. Error sending verification email: {str(e)}")
                return render(request, 'login.html')
        else:
            messages.error(request, "Invalid username or password.")
            return render(request, 'login.html')
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return redirect('home')

@login_required
def share_buy_view(request):
    from .nepse_api_utils import fetch_nepse_stocks_and_ltp
    nepse_stocks = fetch_nepse_stocks_and_ltp()
    if request.method == "POST":
        fetch_from_tms = request.POST.get('fetch_from_tms') == 'true'
        if fetch_from_tms:
            return redirect('fetch_tms_data')
        scrip = request.POST.get('scrip')
        units = request.POST.get('units')
        buying_price = request.POST.get('buying_price')
        transaction_date = request.POST.get('transaction_date')
        try:
            from datetime import datetime
            if not scrip or not scrip.strip():
                raise ValueError("Stock symbol is required")
            scrip = scrip.strip().upper()
            units = int(units) if units else 0
            buying_price = Decimal(str(buying_price)) if buying_price else Decimal('0')
            if units <= 0:
                raise ValueError("Units must be greater than 0")
            if buying_price <= 0:
                raise ValueError("Buying price must be greater than 0")
            if transaction_date:
                transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
            share_buy = Share_Buy.objects.create(
                user=request.user,
                scrip=scrip,
                units=units,
                buying_price=buying_price,
                transaction_date=transaction_date
            )
            costs_data = share_buy.calculate_costs()
            total_share_value = float(units * float(share_buy.buying_price))
            total_payment = float(costs_data['cost_per_share']) * units
            context = {
                'scrip': scrip,
                'units': units,
                'buying_price': float(share_buy.buying_price),
                'total_share_value': total_share_value,
                'total_payment': total_payment,
                'sebon_fee': float(costs_data['sebon_fee']),
                'dp_charge': float(costs_data['dp_charge']),
                'broker_commission': float(costs_data['broker_commission']),
                'cost_per_share': float(costs_data['cost_per_share']),
                'success': True
            }
            return render(request, 'share_buy_result.html', context)
        except (ValueError, TypeError) as e:
            messages.error(request, f'Invalid input data: {e}')
            return render(request, 'share_buy_form.html', {'nepse_stocks': nepse_stocks})
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return render(request, 'share_buy_form.html', {'nepse_stocks': nepse_stocks})
    else:
        return render(request, 'share_buy_form.html', {'nepse_stocks': nepse_stocks})
        

@login_required
def share_sell_view(request):
    if request.method == "POST":
        share_ids = request.POST.get('share_ids')  
        units_sold = request.POST.get('units_sold')
        selling_price = request.POST.get('selling_price')
        transaction_date = request.POST.get('transaction_date')

        try:
            from datetime import datetime
            
            units_sold = int(units_sold) if units_sold else 0
            selling_price = Decimal(str(selling_price)) if selling_price else Decimal('0')
            
            if transaction_date:
                transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
            
            if not share_ids:
                raise ValueError("No shares selected")
                
            share_id_list = [int(id.strip()) for id in share_ids.split(',') if id.strip()]
            shares = Share_Buy.objects.filter(
                id__in=share_id_list, 
                user=request.user, 
                remaining_units__gt=0
            ).order_by('transaction_date', 'id')  # FIFO order
            
            if not shares.exists():
                raise ValueError("No valid shares found to sell")
            
            # Calculate total available units
            total_available = sum(share.remaining_units for share in shares)
            if units_sold > total_available:
                raise ValueError(f"Cannot sell {units_sold} units. Only {total_available} units available.")
            
            # Get scrip name for result display
            scrip_name = shares.first().scrip
            
            # Calculate WACC using ALL purchases for this scrip (not just remaining units)
            # This ensures consistent WACC regardless of how many units have been sold
            all_scrip_purchases = Share_Buy.objects.filter(
                user=request.user, 
                scrip=scrip_name
            ).order_by('transaction_date')
            
            total_cost = Decimal('0')
            total_units = 0
            
            for share in all_scrip_purchases:
                costs_data = share.calculate_costs()
                total_cost += costs_data['total_amount']  # Total cost of this purchase
                total_units += share.units  # Original units purchased (not remaining)
            
            wacc = total_cost / total_units if total_units > 0 else Decimal('0')
            
            # Calculate buy cost using WACC for consistent portfolio tracking
            total_buy_cost = wacc * units_sold
            
            # Generate unique transaction group ID for this sell action
            import uuid
            transaction_group_id = str(uuid.uuid4())
            
            # Distribute sale across shares using FIFO
            remaining_to_sell = units_sold
            share_sales = []
            
            for share in shares:
                if remaining_to_sell <= 0:
                    break
                    
                # Determine how many units to sell from this share
                units_from_this_share = min(remaining_to_sell, share.remaining_units)
                
                # Create Share_Sell record with transaction group ID
                share_sale = Share_Sell.objects.create(
                    user=request.user, 
                    share=share,
                    units_sold=units_from_this_share,
                    selling_price=selling_price,
                    transaction_date=transaction_date,
                    transaction_group=transaction_group_id
                )
                
                share_sales.append(share_sale)
                remaining_to_sell -= units_from_this_share
            
            # Calculate overall profit/loss using the first sale for formulas but aggregate costs
            first_sale = share_sales[0]
            gross_sale = selling_price * units_sold
            
            # Calculate fees using total gross sale
            sebon_fee = gross_sale * Decimal('0.00015')
            dp_charge = Decimal('25.00')
            
            # Broker commission calculation
            if gross_sale <= 50000:
                broker_rate = Decimal('0.36')
            elif gross_sale <= 500000:
                broker_rate = Decimal('0.33')
            elif gross_sale <= 2000000:
                broker_rate = Decimal('0.31')
            elif gross_sale <= 10000000:
                broker_rate = Decimal('0.27')
            else:
                broker_rate = Decimal('0.24')
            
            broker_commission = gross_sale * (broker_rate / 100)
            total_fees = sebon_fee + dp_charge + broker_commission
            net_sale = gross_sale - total_fees
            
            # Calculate profit/loss
            profit_before_tax = net_sale - total_buy_cost
            
            # Calculate holding period for tax (use earliest purchase date)
            earliest_date = min(sale.share.transaction_date for sale in share_sales)
            if transaction_date and earliest_date:
                holding_period_days = (transaction_date - earliest_date).days
            else:
                holding_period_days = 0
            
            # Tax calculation
            if holding_period_days > 365:  # Long-term
                tax_rate = Decimal('0.05')  # 5%
            else:  # Short-term
                tax_rate = Decimal('0.075')  # 7.5%
            
            tax_amount = max(profit_before_tax * tax_rate, Decimal('0')) if profit_before_tax > 0 else Decimal('0')
            final_profit = profit_before_tax - tax_amount
            net_receivable = net_sale - tax_amount
            
            # Calculate profit percentage
            profit_percentage = 0
            if gross_sale > 0:
                profit_percentage = (profit_before_tax / gross_sale) * 100
            
            context = {
                'scrip': scrip_name,
                'units_sold': units_sold,
                'selling_price': float(selling_price),
                'wacc': float(wacc),  # Add WACC for reference
                'gross_sale': float(gross_sale),
                'sebon_fee': float(sebon_fee),
                'dp_charge': float(dp_charge),
                'broker_commission': float(broker_commission),
                'net_sale': float(net_sale),
                'net_receivable': float(net_receivable),
                'total_buy_cost': float(total_buy_cost),
                'profit_before_tax': float(profit_before_tax),
                'tax_amount': float(tax_amount),
                'final_profit': float(final_profit),
                'tax_rate': float(tax_rate) * 100,
                'profit_percentage': profit_percentage,
                'holding_period_days': holding_period_days,
                'success': True
            }
            
            return render(request, 'share_sell_result.html', context)
            
        except Share_Buy.DoesNotExist:
            messages.error(request, "Share not found or you don't have permission to sell it")
            return render(request, 'share_sell_form.html')
        except (ValueError, TypeError) as e:
            messages.error(request, f'Invalid input data: {e}')
            return render(request, 'share_sell_form.html')
        except Exception as e:
            messages.error(request, f'An error occurred: {e}')
            return render(request, 'share_sell_form.html')
    
    else:
        # Group shares by scrip to show consolidated holdings
        available_shares_raw = Share_Buy.objects.filter(user=request.user, remaining_units__gt=0).order_by('scrip', 'transaction_date')
        
        # Group by scrip and calculate totals
        scrip_holdings = {}
        for share in available_shares_raw:
            scrip = share.scrip
            if scrip not in scrip_holdings:
                scrip_holdings[scrip] = {
                    'scrip': scrip,
                    'total_units': 0,
                    'total_cost': Decimal('0'),
                    'share_ids': [],
                    'earliest_date': share.transaction_date,
                    'transactions': []
                }
            
            costs_data = share.calculate_costs()
            total_cost = costs_data['total_amount']
            units = share.remaining_units
            cost_for_remaining = total_cost * (Decimal(units) / Decimal(share.units))
            
            scrip_holdings[scrip]['total_units'] += units
            scrip_holdings[scrip]['total_cost'] += cost_for_remaining
            scrip_holdings[scrip]['share_ids'].append(share.id)
            scrip_holdings[scrip]['transactions'].append(share)
            
            # Keep track of earliest purchase date
            if share.transaction_date < scrip_holdings[scrip]['earliest_date']:
                scrip_holdings[scrip]['earliest_date'] = share.transaction_date
        
        # Convert to list and calculate WACC for each scrip
        available_shares = []
        for scrip, data in scrip_holdings.items():
            # Calculate WACC using ALL purchases for this scrip (not just remaining units)
            all_scrip_purchases = Share_Buy.objects.filter(user=request.user, scrip=scrip)
            total_all_cost = Decimal('0')
            total_all_units = 0
            
            for purchase in all_scrip_purchases:
                costs_data = purchase.calculate_costs()
                total_all_cost += costs_data['total_amount']
                total_all_units += purchase.units
            
            wacc = float(total_all_cost / total_all_units) if total_all_units > 0 else 0
            
            available_shares.append({
                'scrip': scrip,
                'total_units': data['total_units'],
                'wacc': wacc,
                'earliest_date': data['earliest_date'],
                'share_ids': ','.join(map(str, data['share_ids'])),  # Comma-separated IDs for selection
                'transactions': data['transactions']
            })
        
        # Sort by scrip name
        available_shares.sort(key=lambda x: x['scrip'])
        
        context = {
            'available_shares': available_shares
        }
        return render(request, 'share_sell_form.html', context)

@login_required
def sharehub_portfolio_view(request):
    """Comprehensive portfolio dashboard with detailed analytics"""
    user_purchases = Share_Buy.objects.filter(user=request.user)
    user_sales = Share_Sell.objects.filter(user=request.user)
    holdings_data = {}
    sold_stocks_data = {}
    
    for purchase in user_purchases:
        scrip = purchase.scrip
        if scrip not in holdings_data:
            holdings_data[scrip] = {
                'scrip': scrip,
                'total_units': 0,
                'remaining_units': 0,
                'total_investment': Decimal('0'),
                'wacc': Decimal('0'),
                'sold_units': 0,
                'sold_value': Decimal('0'),
                'transactions': []
            }
        
        costs = purchase.calculate_costs()
        holdings_data[scrip]['total_units'] += purchase.units
        holdings_data[scrip]['remaining_units'] += purchase.remaining_units
        holdings_data[scrip]['total_investment'] += costs['cost_per_share'] * purchase.units
        holdings_data[scrip]['transactions'].append(purchase)
    
    for scrip, data in holdings_data.items():
        if data['total_units'] > 0:
            data['wacc'] = data['total_investment'] / data['total_units']
    
    for sale in user_sales:
        scrip = sale.scrip
        profit_loss = sale.calculate_profit_loss()
        
        if scrip in holdings_data:
            holdings_data[scrip]['sold_units'] += sale.units_sold
            holdings_data[scrip]['sold_value'] += profit_loss['gross_sale']
        
        if scrip not in sold_stocks_data:
            sold_stocks_data[scrip] = {
                'scrip': scrip,
                'total_units_sold': 0,
                'total_sale_value': Decimal('0'),
                'total_profit_loss': Decimal('0'),
                'total_tax_paid': Decimal('0'),
                'avg_selling_price': Decimal('0'),
                'wacc': holdings_data.get(scrip, {}).get('wacc', Decimal('0')),
                'transactions': []
            }
        
        sold_stocks_data[scrip]['total_units_sold'] += sale.units_sold
        sold_stocks_data[scrip]['total_sale_value'] += profit_loss['gross_sale']
        sold_stocks_data[scrip]['total_profit_loss'] += profit_loss['final_profit']
        sold_stocks_data[scrip]['total_tax_paid'] += profit_loss['tax_amount']
        sold_stocks_data[scrip]['transactions'].append(sale)
    
    for scrip, data in sold_stocks_data.items():
        if data['total_units_sold'] > 0:
            data['avg_selling_price'] = data['total_sale_value'] / data['total_units_sold']
    
    holdings = []
    for scrip, data in holdings_data.items():
        if data['remaining_units'] > 0: 
            current_price = data['wacc'] * Decimal('1.08')  
            holding = {
                'scrip': scrip,
                'remaining_units': data['remaining_units'],
                'sold_units': data['sold_units'],
                'total_investment': data['total_investment'],
                'wacc': data['wacc'],
                'sold_value': data['sold_value'],
                'current_price': current_price,
                'current_value': current_price * data['remaining_units'],
                'current_investment': data['wacc'] * data['remaining_units'],
                'price_change': current_price - data['wacc'],
                'percentage_change': ((current_price - data['wacc']) / data['wacc'] * 100) if data['wacc'] > 0 else 0,
                'estimated_profit': (current_price - data['wacc']) * data['remaining_units'],
                'profit_percentage': ((current_price - data['wacc']) / data['wacc'] * 100) if data['wacc'] > 0 else 0,
                'unrealized_gain': (current_price - data['wacc']) * data['remaining_units'],
                'realized_gain': sum(
                    sale.calculate_profit_loss()['final_profit'] 
                    for sale in user_sales.filter(share__scrip=scrip)
                ) if data['sold_units'] > 0 else Decimal('0'),
                'receivable_amount': current_price * data['remaining_units'],
                'todays_gain': (current_price - data['wacc']) * data['remaining_units'] * Decimal('0.02'),  
            }
            holdings.append(holding)
    
    sold_stocks = []
    for scrip, data in sold_stocks_data.items():
        sold_stock = {
            'scrip': scrip,
            'total_units_sold': data['total_units_sold'],
            'total_sale_value': data['total_sale_value'],
            'avg_selling_price': data['avg_selling_price'],
            'wacc': data['wacc'],
            'total_profit_loss': data['total_profit_loss'],
            'total_tax_paid': data['total_tax_paid'],
            'profit_percentage': ((data['avg_selling_price'] - data['wacc']) / data['wacc'] * 100) if data['wacc'] > 0 else 0,
        }
        sold_stocks.append(sold_stock)
    
    total_units = sum(h['remaining_units'] for h in holdings)
    total_sold_units = sum(data['sold_units'] for data in holdings_data.values())
    total_investment = sum(data['total_investment'] for data in holdings_data.values())
    current_value = sum(h['current_value'] for h in holdings)
    total_sold_value = sum(data['sold_value'] for data in holdings_data.values())
    estimated_profit = sum(h['estimated_profit'] for h in holdings)
    profit_percentage = (estimated_profit / total_investment * 100) if total_investment > 0 else 0
    todays_gain = sum(h['todays_gain'] for h in holdings)
    current_investment = sum(h['current_investment'] for h in holdings)
    current_profit_percentage = (sum(h['unrealized_gain'] for h in holdings) / current_investment * 100) if current_investment > 0 else 0
    realized_gain = sum(h['realized_gain'] for h in holdings)
    unrealized_gain = sum(h['unrealized_gain'] for h in holdings)
    receivable_amount = sum(h['receivable_amount'] for h in holdings)
    
    context = {
        'holdings': holdings,
        'sold_stocks': sold_stocks,
        'total_units': total_units,
        'total_sold_units': total_sold_units,
        'total_investment': total_investment,
        'current_value': current_value,
        'total_sold_value': total_sold_value,
        'estimated_profit': estimated_profit,
        'profit_percentage': profit_percentage,
        'todays_gain': todays_gain,
        'current_investment': current_investment,
        'current_profit_percentage': current_profit_percentage,
        'realized_gain': realized_gain,
        'unrealized_gain': unrealized_gain,
        'receivable_amount': receivable_amount,
    }
    
    return render(request, 'sharehub_portfolio.html', context)

@login_required
def holding_detail_view(request, scrip):
    """Detailed view for a specific holding showing all transactions and costs"""
    try:
        buy_transactions = Share_Buy.objects.filter(user=request.user, scrip=scrip).order_by('transaction_date')
        
        if not buy_transactions.exists():
            messages.error(request, f'No holdings found for {scrip}')
            return redirect('sharehub_portfolio')
        
        sell_transactions = Share_Sell.objects.filter(
            user=request.user, 
            share__scrip=scrip
        ).order_by('transaction_date')
        
        total_units = sum(t.units for t in buy_transactions)
        available_units = sum(t.remaining_units for t in buy_transactions)
        sold_units = sum(t.units_sold for t in sell_transactions)
        
        # Calculate WACC
        total_cost = Decimal('0')
        for transaction in buy_transactions:
            costs = transaction.calculate_costs()
            total_cost += costs['total_amount']
        
        wacc = total_cost / total_units if total_units > 0 else Decimal('0')
        
        current_price = wacc * Decimal('1.08')
        current_value = current_price * available_units
        
        unrealized_pnl = (current_price - wacc) * available_units
        realized_pnl = sum(
            t.calculate_profit_loss()['final_profit'] 
            for t in sell_transactions
        )
        
        buy_transactions_data = []
        for transaction in buy_transactions:
            costs = transaction.calculate_costs()
            buy_transactions_data.append({
                'transaction': transaction,
                'costs': costs,
                'gross_amount': transaction.units * transaction.buying_price,
                'broker_rate': transaction.get_broker_rate()
            })
        
        sell_transactions_data = []
        for transaction in sell_transactions:
            profit_loss = transaction.calculate_profit_loss()
            sell_transactions_data.append({
                'transaction': transaction,
                'profit_loss': profit_loss,
                'broker_rate': transaction.get_broker_rate()
            })
        
        context = {
            'scrip': scrip,
            'total_units': total_units,
            'available_units': available_units,
            'sold_units': sold_units,
            'wacc': wacc,
            'total_investment': total_cost,
            'current_value': current_value,
            'unrealized_pnl': unrealized_pnl,
            'realized_pnl': realized_pnl,
            'buy_transactions': buy_transactions_data,
            'sell_transactions': sell_transactions_data,
        }
        
        return render(request, 'holding_detail.html', context)
        
    except Exception as e:
        messages.error(request, f'Error loading holding details: {str(e)}')
        return redirect('sharehub_portfolio')

@login_required
def sold_holding_detail_view(request, scrip):
    """Detailed view for sold holdings showing all sale transactions and profit/loss breakdown"""
    try:
        sell_transactions = Share_Sell.objects.filter(
            user=request.user, 
            share__scrip=scrip
        ).order_by('transaction_date')
        
        if not sell_transactions.exists():
            messages.error(request, f'No sold holdings found for {scrip}')
            return redirect('sharehub_portfolio')
        
        buy_transactions = Share_Buy.objects.filter(
            user=request.user, 
            scrip=scrip
        ).order_by('transaction_date')
        
        # Calculate WACC from buy transactions
        total_cost = Decimal('0')
        total_units = 0
        for transaction in buy_transactions:
            costs = transaction.calculate_costs()
            total_cost += costs['total_amount']
            total_units += transaction.units
        
        wacc = total_cost / total_units if total_units > 0 else Decimal('0')
        
        # Calculate aggregated data
        total_units_sold = sum(t.units_sold for t in sell_transactions)
        total_sale_value = Decimal('0')
        total_profit_loss = Decimal('0')
        total_tax_paid = Decimal('0')
        total_commission_paid = Decimal('0')
        total_fees_paid = Decimal('0')
        
        # Prepare transaction data with calculations
        sell_transactions_data = []
        for transaction in sell_transactions:
            profit_loss = transaction.calculate_profit_loss()
            sell_transactions_data.append({
                'transaction': transaction,
                'profit_loss': profit_loss,
                'broker_rate': transaction.get_broker_rate()
            })
            
            total_sale_value += profit_loss['gross_sale']
            total_profit_loss += profit_loss['final_profit']
            total_tax_paid += profit_loss['tax_amount']
            total_commission_paid += profit_loss['broker_commission']
            total_fees_paid += profit_loss['sebon_fee'] + profit_loss['dp_charge']
        
        avg_selling_price = total_sale_value / total_units_sold if total_units_sold > 0 else Decimal('0')
        profit_percentage = ((avg_selling_price - wacc) / wacc * 100) if wacc > 0 else 0
        total_buy_cost = wacc * total_units_sold
        
        context = {
            'scrip': scrip,
            'total_units_sold': total_units_sold,
            'total_sale_value': total_sale_value,
            'avg_selling_price': avg_selling_price,
            'wacc': wacc,
            'total_buy_cost': total_buy_cost,
            'total_profit_loss': total_profit_loss,
            'profit_percentage': profit_percentage,
            'total_tax_paid': total_tax_paid,
            'total_commission_paid': total_commission_paid,
            'total_fees_paid': total_fees_paid,
            'sell_transactions': sell_transactions_data,
        }
        
        return render(request, 'sold_holding_detail.html', context)
        
    except Exception as e:
        messages.error(request, f'Error loading sold holding details: {str(e)}')
        return redirect('sharehub_portfolio')

@login_required
def sharehub_portfolio_view(request):
    """ShareHub Nepal style portfolio dashboard with modern design"""
    user_purchases = Share_Buy.objects.filter(user=request.user)
    user_sales = Share_Sell.objects.filter(user=request.user)
    from .nepse_api_utils import fetch_nepse_stocks_and_ltp
    nepse_stocks = fetch_nepse_stocks_and_ltp()
    nepse_ltp_map = {stock['symbol']: stock for stock in nepse_stocks}

    current_holdings_data = {}
    sold_holdings_data = {}

    for purchase in user_purchases:
        scrip = purchase.scrip
        if scrip not in current_holdings_data:
            current_holdings_data[scrip] = {
                'scrip': scrip,
                'total_units': 0,
                'remaining_units': 0,
                'total_investment': Decimal('0'),
                'wacc': Decimal('0'),
                'transactions': []
            }
        costs = purchase.calculate_costs()
        current_holdings_data[scrip]['total_units'] += purchase.units
        current_holdings_data[scrip]['remaining_units'] += purchase.remaining_units
        current_holdings_data[scrip]['total_investment'] += costs['total_amount']
        current_holdings_data[scrip]['transactions'].append(purchase)

    for scrip, data in current_holdings_data.items():
        if data['total_units'] > 0:
            data['wacc'] = data['total_investment'] / data['total_units']

    for sale in user_sales:
        scrip = sale.share.scrip
        if scrip not in sold_holdings_data:
            sold_holdings_data[scrip] = {
                'scrip': scrip,
                'total_sold_units': 0,
                'total_cost': Decimal('0'),
                'total_sale_value': Decimal('0'),
                'total_tax': Decimal('0'),
                'realized_pnl': Decimal('0'),
                'transactions': []
            }
        profit_loss = sale.calculate_profit_loss()
        sold_holdings_data[scrip]['total_sold_units'] += sale.units_sold
        sold_holdings_data[scrip]['total_cost'] += profit_loss['total_buy_cost']
        sold_holdings_data[scrip]['total_sale_value'] += profit_loss['gross_sale']
        sold_holdings_data[scrip]['total_tax'] += profit_loss['tax_amount']
        sold_holdings_data[scrip]['realized_pnl'] += profit_loss['final_profit']
        sold_holdings_data[scrip]['transactions'].append(sale)

    current_holdings = []
    all_holdings = []

    for scrip, data in current_holdings_data.items():
        nepse = nepse_ltp_map.get(scrip, {})
        ltp = nepse.get('ltp')
        change = nepse.get('change')
        change_percent = nepse.get('changePercent')
        current_price = Decimal(str(ltp)) if ltp else (data['wacc'] * Decimal('1.08') if data['wacc'] > 0 else Decimal('0'))
        price_change = Decimal(str(change)) if change is not None else (current_price - data['wacc'] if data['wacc'] > 0 else Decimal('0'))
        percentage_change = Decimal(str(change_percent)) if change_percent is not None else ((price_change / data['wacc'] * 100) if data['wacc'] > 0 else 0)
        current_value = current_price * data['remaining_units']
        current_investment = data['wacc'] * data['remaining_units']
        unrealized_pnl = current_value - current_investment
        sold_data = sold_holdings_data.get(scrip, {})
        holding_data = {
            'scrip': scrip,
            'total_units': data['total_units'],
            'remaining_units': data['remaining_units'],
            'wacc': data['wacc'],
            'total_investment': data['total_investment'],
            'current_value': current_value,
            'current_price': current_price,
            'price_change': price_change,
            'percentage_change': percentage_change,
            'unrealized_pnl': unrealized_pnl,
            'current_investment': current_investment,
            'ltp': ltp,
            'ltp_change': change,
            'ltp_change_percent': change_percent,
            'transactions': data['transactions'],
            'sold_units': sold_data.get('total_sold_units', 0),
            'realized_pnl': sold_data.get('realized_pnl', Decimal('0')),
            'sold_transactions': sold_data.get('transactions', [])
        }
        if data['remaining_units'] > 0:
            current_holdings.append(holding_data)
        all_holdings.append(holding_data)

    for scrip, data in sold_holdings_data.items():
        if scrip not in current_holdings_data:
            nepse = nepse_ltp_map.get(scrip, {})
            avg_selling_price = data['total_sale_value'] / data['total_sold_units'] if data['total_sold_units'] > 0 else Decimal('0')
            avg_wacc = data['total_cost'] / data['total_sold_units'] if data['total_sold_units'] > 0 else Decimal('0')
            holding_data = {
                'scrip': scrip,
                'total_units': data['total_sold_units'],
                'remaining_units': 0,
                'wacc': avg_wacc,
                'total_investment': data['total_cost'],
                'current_value': Decimal('0'),
                'current_price': avg_selling_price,
                'price_change': Decimal('0'),
                'percentage_change': 0,
                'unrealized_pnl': Decimal('0'),
                'current_investment': Decimal('0'),
                'ltp': nepse.get('ltp'),
                'ltp_change': nepse.get('change'),
                'ltp_change_percent': nepse.get('changePercent'),
                'transactions': [],
                'sold_units': data['total_sold_units'],
                'realized_pnl': data['realized_pnl'],
                'sold_transactions': data['transactions']
            }
            all_holdings.append(holding_data)

    total_investment = sum(h['total_investment'] for h in current_holdings)
    total_current_value = sum(h['current_value'] for h in current_holdings)
    total_unrealized_pnl = total_current_value - sum(h['current_investment'] for h in current_holdings)
    total_realized_pnl = sum(data['realized_pnl'] for data in sold_holdings_data.values())
    net_portfolio_value = total_current_value + total_realized_pnl

    # Prepare separate transaction lists for easier template rendering
    all_buy_transactions = []
    all_sell_transactions = []
    
    for holding in all_holdings:
        all_buy_transactions.extend(holding['transactions'])
        all_sell_transactions.extend(holding['sold_transactions'])
    
    # Sort transactions by date (newest first)
    all_buy_transactions.sort(key=lambda x: x.transaction_date, reverse=True)
    all_sell_transactions.sort(key=lambda x: x.transaction_date, reverse=True)

    context = {
        'current_holdings': current_holdings,
        'all_holdings': all_holdings,
        'current_holdings_count': len(current_holdings),
        'all_holdings_count': len(all_holdings),
        'total_investment': total_investment,
        'total_current_value': total_current_value,
        'total_unrealized_pnl': total_unrealized_pnl,
        'total_realized_pnl': total_realized_pnl,
        'net_portfolio_value': net_portfolio_value,
        'all_buy_transactions': all_buy_transactions,
        'all_sell_transactions': all_sell_transactions,
    }
    return render(request, 'sharehub_portfolio.html', context)

@login_required
def sharehub_holding_detail_view(request, scrip):
    """ShareHub style detailed holding view"""
    try:
        # Get all buy transactions for this scrip
        buy_transactions = Share_Buy.objects.filter(user=request.user, scrip=scrip).order_by('transaction_date')
        
        if not buy_transactions.exists():
            messages.error(request, f'No holdings found for {scrip}')
            return redirect('sharehub_portfolio')
        
        # Get all sell transactions for this scrip (ordered by newest first)
        sell_transactions = Share_Sell.objects.filter(
            user=request.user, 
            share__scrip=scrip
        ).order_by('-transaction_date', '-id')  # Latest transactions first
        
        # Calculate summary data
        total_units = sum(t.units for t in buy_transactions)
        available_units = sum(t.remaining_units for t in buy_transactions)
        sold_units = sum(t.units_sold for t in sell_transactions)
        
        # Calculate WACC: Total cost of all purchases / Total units purchased
        total_cost_all_purchases = Decimal('0')
        for transaction in buy_transactions:
            costs = transaction.calculate_costs()
            total_cost_all_purchases += costs['total_amount']
        
        wacc = total_cost_all_purchases / total_units if total_units > 0 else Decimal('0')
        
        # Calculate total investment (same as total cost)
        total_investment = total_cost_all_purchases
        
        # Calculate realized P&L
        realized_pnl = sum(
            t.calculate_profit_loss()['final_profit'] 
            for t in sell_transactions
        )
        
        # Prepare transaction data
        buy_transactions_data = []
        for transaction in buy_transactions:
            costs = transaction.calculate_costs()
            buy_transactions_data.append({
                'transaction': transaction,
                'costs': costs,
                'gross_amount': transaction.units * transaction.buying_price,
                'broker_rate': transaction.get_broker_rate()
            })
        
        sell_transactions_data = []
        
        # Group sell transactions by transaction_group to show original user actions
        from collections import defaultdict
        grouped_sells = defaultdict(list)
        
        for transaction in sell_transactions:
            # If transaction_group exists, use it; otherwise group by date and price (for old data)
            group_key = transaction.transaction_group if transaction.transaction_group else f"{transaction.transaction_date}_{transaction.selling_price}"
            grouped_sells[group_key].append(transaction)
        
        # Process each group as a single transaction
        for group_key, transactions in grouped_sells.items():
            # Calculate totals for this group (original user transaction)
            total_units_sold = sum(t.units_sold for t in transactions)
            avg_selling_price = transactions[0].selling_price  # Same for all in group
            transaction_date = transactions[0].transaction_date  # Same for all in group
            
            # Calculate total buy cost using the overall WACC (not individual transaction WACCs)
            total_buy_cost = wacc * total_units_sold
            
            # Calculate fees for the ORIGINAL transaction (not summing split fees)
            # This is how the user originally made the transaction
            total_gross_sale = avg_selling_price * total_units_sold
            
            # Calculate fees based on the original total gross sale
            total_sebon_fee = total_gross_sale * Decimal('0.00015')
            total_dp_charge = Decimal('25.00')  # DP charge is fixed per transaction, not per split
            
            # Broker commission calculation based on total gross sale
            if total_gross_sale <= 50000:
                broker_rate = Decimal('0.36')
            elif total_gross_sale <= 500000:
                broker_rate = Decimal('0.33')
            elif total_gross_sale <= 2000000:
                broker_rate = Decimal('0.31')
            elif total_gross_sale <= 10000000:
                broker_rate = Decimal('0.27')
            else:
                broker_rate = Decimal('0.24')
                
            total_broker_commission = total_gross_sale * (broker_rate / 100)
            total_net_sale = total_gross_sale - total_sebon_fee - total_dp_charge - total_broker_commission
            
            # Recalculate profit/loss with correct WACC-based buy cost
            total_profit_before_tax = total_net_sale - total_buy_cost
            
            # Calculate tax based on the representative transaction's holding period
            representative_transaction = transactions[0]
            holding_period_days = (transaction_date - representative_transaction.share.transaction_date).days
            
            # Tax calculation
            if total_profit_before_tax > 0:
                if holding_period_days >= 365:  # 1 year or more
                    tax_rate = Decimal('0.05')  # 5% tax
                else:  # Less than 1 year
                    tax_rate = Decimal('0.075')  # 7.5% tax
                total_tax_amount = total_profit_before_tax * tax_rate
            else:
                total_tax_amount = Decimal('0')
                tax_rate = Decimal('0.075')  # Default for display
            
            total_final_profit = total_profit_before_tax - total_tax_amount
            
            # Calculate actual receivable amount (net sale minus capital gain tax)
            total_receivable_amount = total_net_sale - total_tax_amount
            
            # Create a representative transaction object with combined data
            combined_profit_loss = {
                'gross_sale': total_gross_sale,
                'net_sale': total_net_sale,
                'receivable_amount': total_receivable_amount,  # Add proper receivable amount
                'total_buy_cost': total_buy_cost,
                'profit_before_tax': total_profit_before_tax,
                'tax_amount': total_tax_amount,
                'final_profit': total_final_profit,
                'sebon_fee': total_sebon_fee,  # Calculated for original transaction amount
                'dp_charge': total_dp_charge,  # Fixed fee per transaction (not per split)  
                'broker_commission': total_broker_commission,  # Calculated for original transaction amount
                'holding_period_days': holding_period_days,
                'tax_rate': tax_rate,
                'tax_rate_percentage': float(tax_rate * 100),
                'wacc': wacc,  # Use the overall WACC, not individual transaction WACC
            }
            
            # Create a mock transaction object with combined data
            class CombinedTransaction:
                def __init__(self, transactions, total_units, calculated_broker_rate):
                    self.original_transactions = transactions
                    self.id = transactions[0].id  # Use first transaction's ID as representative
                    self.units_sold = total_units
                    self.selling_price = transactions[0].selling_price
                    self.transaction_date = transactions[0].transaction_date
                    self.share = transactions[0].share
                    self.transaction_group = transactions[0].transaction_group
                    self.user = transactions[0].user
                    self._broker_rate = calculated_broker_rate
                
                def get_broker_rate(self):
                    return float(self._broker_rate)
                
                @property
                def is_grouped(self):
                    """Return True if this represents multiple transactions"""
                    return len(self.original_transactions) > 1
                
                @property  
                def scrip(self):
                    """Get the scrip name from the related Share_Buy"""
                    return self.share.scrip
            
            combined_transaction = CombinedTransaction(transactions, total_units_sold, broker_rate)
            
            sell_transactions_data.append({
                'transaction': combined_transaction,
                'profit_loss': combined_profit_loss,
                'broker_rate': float(broker_rate),  # Use the calculated broker rate for the combined transaction
                'is_grouped': len(transactions) > 1,  # Flag to indicate if this was grouped
                'original_count': len(transactions),  # Number of original FIFO splits
                'individual_transactions': [  # Add individual transactions for template compatibility
                    {
                        'transaction': t,
                        'profit_loss': t.calculate_profit_loss(),
                        'broker_rate': t.get_broker_rate()
                    } for t in transactions
                ] if len(transactions) > 1 else None
            })
        
        # Group sell transactions - show each individual sell action as it was made
        # This will show the actual sell transactions as the user made them
        # Note: Each user sell action might create multiple Share_Sell records due to FIFO,
        # but we'll identify original transactions by grouping by transaction_group or date/price
        
        # Combine all transactions for the template
        all_transactions = []
        
        # Add buy transactions with type indicator
        for buy_data in buy_transactions_data:
            buy_data['type'] = 'buy'
            all_transactions.append(buy_data)
        
        # Add sell transactions without grouping (show as individual user actions)
        for sell_data in sell_transactions_data:
            sell_data['type'] = 'sell'
            all_transactions.append(sell_data)
        
        # Sort all transactions by date (latest first)
        all_transactions.sort(
            key=lambda x: x['transaction'].transaction_date, 
            reverse=True
        )
        
        # Calculate sold value (total receivable amount after tax)
        total_sold_receivable = sum(
            t['profit_loss']['receivable_amount'] 
            for t in sell_transactions_data
        )
        
        # Fetch LTP and change for this scrip
        from .nepse_api_utils import fetch_nepse_stocks_and_ltp
        nepse_stocks = fetch_nepse_stocks_and_ltp()
        ltp = None
        change = None
        changePercent = None
        high = None
        low = None
        open_ = None
        close = None
        volume = None
        turnover = None
        today_loss = None
        today_gain = None
        for stock in nepse_stocks:
            if stock['symbol'] == scrip:
                ltp = stock.get('ltp')
                change = stock.get('change')
                changePercent = stock.get('changePercent')
                high = stock.get('high')
                low = stock.get('low')
                open_ = stock.get('open')
                close = stock.get('close')
                volume = stock.get('volume')
                turnover = stock.get('turnover')
                today_loss = stock.get('today_loss')
                today_gain = stock.get('today_gain')
                break

        # Calculate unrealized gain (for available units)
        unrealized_gain = None
        current_value = None
        profit_percent = None
        if ltp is not None and available_units > 0 and wacc > 0:
            try:
                unrealized_gain = (ltp - float(wacc)) * available_units
                current_value = ltp * available_units
                if total_investment:
                    profit_percent = (unrealized_gain / float(total_investment)) * 100
            except Exception:
                unrealized_gain = None
                current_value = None
                profit_percent = None

        context = {
            'scrip': scrip,
            'total_units': total_units,
            'available_units': available_units,
            'sold_units': sold_units,
            'wacc': wacc,
            'total_investment': total_investment,
            'total_sold_receivable': total_sold_receivable,
            'realized_pnl': realized_pnl,
            'buy_transactions': buy_transactions_data,
            'sell_transactions': sell_transactions_data,
            'all_transactions': all_transactions,  # Combined transactions for template
            'ltp': ltp,
            'change': change,
            'changePercent': changePercent,
            'high': high,
            'low': low,
            'open': open_,
            'close': close,
            'volume': volume,
            'turnover': turnover,
            'today_loss': today_loss,
            'today_gain': today_gain,
            'unrealized_gain': unrealized_gain,
            'current_value': current_value,
            'profit_percent': profit_percent,
        }

        return render(request, 'sharehub_holding_detail.html', context)
        
    except Exception as e:
        messages.error(request, f'Error loading holding details: {str(e)}')
        return redirect('sharehub_portfolio')

@login_required
def sharehub_sold_holding_detail_view(request, scrip):
    """ShareHub style sold holding detail view"""
    try:
        # Get all sell transactions for this scrip
        sell_transactions = Share_Sell.objects.filter(
            user=request.user, 
            share__scrip=scrip
        ).order_by('transaction_date')
        
        if not sell_transactions.exists():
            messages.error(request, f'No sold holdings found for {scrip}')
            return redirect('sharehub_portfolio')
        
        # Get related buy transactions
        buy_transaction_ids = sell_transactions.values_list('share_id', flat=True).distinct()
        buy_transactions = Share_Buy.objects.filter(id__in=buy_transaction_ids).order_by('transaction_date')
        
        # Calculate summary data
        total_sold_units = sum(t.units_sold for t in sell_transactions)
        total_sale_value = sum(t.calculate_profit_loss()['gross_sale'] for t in sell_transactions)
        total_cost = sum(t.calculate_profit_loss()['total_buy_cost'] for t in sell_transactions)
        total_tax = sum(t.calculate_profit_loss()['tax_amount'] for t in sell_transactions)
        realized_pnl = sum(t.calculate_profit_loss()['final_profit'] for t in sell_transactions)
        
        # Calculate averages
        avg_sell_price = total_sale_value / total_sold_units if total_sold_units > 0 else Decimal('0')
        avg_wacc = total_cost / total_sold_units if total_sold_units > 0 else Decimal('0')
        return_percentage = (realized_pnl / total_cost * 100) if total_cost > 0 else 0
        
        # Prepare transaction data
        buy_transactions_data = []
        for transaction in buy_transactions:
            costs = transaction.calculate_costs()
            buy_transactions_data.append({
                'transaction': transaction,
                'costs': costs,
                'gross_amount': transaction.units * transaction.buying_price,
                'broker_rate': transaction.get_broker_rate()
            })
        
        sell_transactions_data = []
        for transaction in sell_transactions:
            profit_loss = transaction.calculate_profit_loss()
            sell_transactions_data.append({
                'transaction': transaction,
                'profit_loss': profit_loss,
                'broker_rate': transaction.get_broker_rate()
            })
        
        context = {
            'scrip': scrip,
            'total_sold_units': total_sold_units,
            'total_sale_value': total_sale_value,
            'total_cost': total_cost,
            'total_tax': total_tax,
            'realized_pnl': realized_pnl,
            'avg_sell_price': avg_sell_price,
            'avg_wacc': avg_wacc,
            'return_percentage': return_percentage,
            'buy_transactions': buy_transactions_data,
            'sell_transactions': sell_transactions_data,
        }
        
        return render(request, 'sharehub_sold_detail.html', context)
        
    except Exception as e:
        messages.error(request, f'Error loading sold holding details: {str(e)}')
        return redirect('sharehub_portfolio')

def password_reset_request_view(request):
    """Handle password reset request"""
    if request.method == "POST":
        email = request.POST.get('email')
        
        try:
            user = User.objects.get(email=email)
            
            # Generate password reset token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Create reset URL
            reset_url = request.build_absolute_uri(f'/reset-password/{uid}/{token}/')
            
            # Send password reset email
            subject = 'Code Bulls - Password Reset Request'
            message = f'''
            Hello {user.first_name or user.username},
            
            You have requested to reset your password for Code Bulls.
            
            Please click the link below to reset your password:
            {reset_url}
            
            If you did not request this password reset, please ignore this email.
            
            This link will expire in 24 hours.
            
            Best regards,
            Code Bulls Team
            '''
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            
            messages.success(request, f'Password reset instructions have been sent to {email}. Please check your inbox.')
            return redirect('login')
            
        except User.DoesNotExist:
            messages.error(request, 'No account found with that email address.')
            return render(request, 'password_reset_request.html')
        except Exception as e:
            messages.error(request, f'Error sending password reset email: {str(e)}')
            return render(request, 'password_reset_request.html')
    
    return render(request, 'password_reset_request.html')

def password_reset_confirm_view(request, uidb64, token):
    """Handle password reset confirmation"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    
    if user is not None and default_token_generator.check_token(user, token):
        if request.method == "POST":
            password = request.POST.get('password')
            confirm_password = request.POST.get('confirm_password')
            
            if password != confirm_password:
                messages.error(request, 'Passwords do not match!')
                return render(request, 'password_reset_confirm.html', {'valid_link': True})
            
            if len(password) < 8:
                messages.error(request, 'Password must be at least 8 characters long!')
                return render(request, 'password_reset_confirm.html', {'valid_link': True})
            
            # Reset the password
            user.set_password(password)
            user.save()
            
            messages.success(request, 'Your password has been reset successfully! You can now log in with your new password.')
            return redirect('login')
        
        return render(request, 'password_reset_confirm.html', {'valid_link': True})
    else:
        messages.error(request, 'The password reset link is invalid or has expired.')
        return render(request, 'password_reset_confirm.html', {'valid_link': False})


@login_required
def fetch_tms_data_view(request):
    """
    View to fetch data from TMS Nepse website using manual login - No credentials stored
    """
    # Get user's TMS settings - only server number, no credentials
    try:
        profile = request.user.profile_ver
        default_tms_number = profile.tms_server or 52
    except:
        default_tms_number = 52
    
    if request.method == 'POST':
        import logging
        logger = logging.getLogger("django")
        tms_number_raw = request.POST.get('tms_number', default_tms_number)
        settlement_type = request.POST.get('settlement_type', 'PaymentDue')
        tms_number = str(default_tms_number)
        try:
            tms_number_str = str(tms_number_raw).strip()
            tms_number_nozero = tms_number_str.lstrip('0')
            if tms_number_nozero == '':
                tms_number_nozero = '0'
            logger.debug(f"TMS number input: raw='{tms_number_raw}', stripped='{tms_number_str}', nozero='{tms_number_nozero}'")
            if tms_number_nozero.isdigit():
                tms_number_int = int(tms_number_nozero)
                if 1 <= tms_number_int <= 99:
                    tms_number = str(tms_number_int)
                else:
                    logger.warning(f"TMS number out of range: {tms_number_int}, using default {default_tms_number}")
            else:
                logger.warning(f"TMS number not digit after strip: '{tms_number_nozero}', using default {default_tms_number}")
        except Exception as e:
            logger.warning(f"TMS number parse error: {e}, raw value: {tms_number_raw}")
            tms_number = str(default_tms_number)
        logger.info(f"TMS fetch: raw={tms_number_raw}, parsed={tms_number}, settlement_type={settlement_type}")

        try:
            # Import here to avoid issues if playwright is not installed
            from .tms_service import fetch_tms_data

            messages.info(
                request, 
                'A browser window will open for you to login to TMS manually. '
                'You have 30 seconds to fill the form, then the system will start monitoring for login completion.'
            )

            result = fetch_tms_data(
                user=request.user,
                tms_number=tms_number,
                settlement_type=settlement_type
            )

            if result['success']:
                messages.success(
                    request, 
                    f'Successfully fetched {result["records_found"]} records, '
                    f'saved {result["records_saved"]} new share purchase records.'
                )

                # Show details of saved records
                for record in result['data']:
                    messages.info(
                        request,
                        f'Added: {record.scrip} - {record.units} units @ Rs.{record.buying_price}'
                    )

                return redirect('dashboard')
            else:
                messages.error(request, f'Failed to fetch data: {result["error"]}')

        except ImportError:
            messages.error(
                request, 
                'Playwright is not installed. Please run: pip install playwright && playwright install'
            )
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
    
    return render(request, 'fetch_tms_data.html', {
        'default_tms_number': default_tms_number
    })


@login_required
def settings_view(request):
    """User settings page for updating TMS configuration - No credentials stored"""
    if request.method == 'POST':
        try:
            profile = request.user.profile_ver
            
            # Update TMS configuration (server number only, no credentials)
            tms_server_number = request.POST.get('tms_server_number')
            
            if tms_server_number:
                profile.tms_server = int(tms_server_number)
                profile.tms_configured = True
                profile.save()
                
                messages.success(request, 'TMS server settings updated successfully!')
            else:
                messages.error(request, 'Please select a TMS server number.')
                
            return redirect('settings')
            
        except Profile_ver.DoesNotExist:
            messages.error(request, 'Profile not found. Please contact support.')
        except ValueError:
            messages.error(request, 'Invalid TMS server number. Please enter a valid number.')
        except Exception as e:
            messages.error(request, f'Error updating TMS settings: {str(e)}')
    
    try:
        profile = request.user.profile_ver
    except Profile_ver.DoesNotExist:
        # Create profile if it doesn't exist
        profile = Profile_ver.objects.create(
            user=request.user,
            uid=str(uuid.uuid4())
        )
    
    return render(request, 'settings.html', {'profile': profile})




@login_required
def edit_buy_transaction(request, transaction_id):
    """Edit a buy transaction"""
    try:
        transaction = Share_Buy.objects.get(id=transaction_id, user=request.user)
    except Share_Buy.DoesNotExist:
        messages.error(request, 'Transaction not found.')
        return redirect('sharehub_portfolio')
    
    if request.method == 'POST':
        try:
            from datetime import datetime
            
            # Get form data
            units = int(request.POST.get('units', transaction.units))
            buying_price = Decimal(str(request.POST.get('buying_price', transaction.buying_price)))
            transaction_date = request.POST.get('transaction_date')
            
            # Validate input
            if units <= 0:
                raise ValueError("Units must be greater than 0")
            if buying_price <= 0:
                raise ValueError("Buying price must be greater than 0")
            
            # Parse date
            if transaction_date:
                transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
            else:
                transaction_date = transaction.transaction_date
            
            # Update transaction
            old_units = transaction.units
            old_remaining = transaction.remaining_units
            
            # Calculate how many units have been sold from this transaction
            total_sold_from_this = old_units - old_remaining
            
            # Validate that new units is not less than what has already been sold
            if units < total_sold_from_this:
                raise ValueError(f"Cannot reduce units to {units}. {total_sold_from_this} units have already been sold from this transaction.")
            
            # Update the transaction
            transaction.units = units
            transaction.buying_price = buying_price
            transaction.transaction_date = transaction_date
            
            # Calculate new remaining units
            transaction.remaining_units = units - total_sold_from_this
            
            transaction.save()
            
            messages.success(request, f'Transaction updated successfully for {transaction.scrip}. Remaining units recalculated.')
            return redirect('sharehub_holding_detail', scrip=transaction.scrip)
            
        except (ValueError, TypeError) as e:
            messages.error(request, f'Invalid input: {e}')
        except Exception as e:
            messages.error(request, f'Error updating transaction: {e}')
    
    # GET request - show edit form
    context = {
        'transaction': transaction,
        'is_edit': True,
        'scrip': transaction.scrip
    }
    return render(request, 'share_buy_form.html', context)


@login_required
def edit_sell_transaction(request, transaction_id):
    """Edit a sell transaction"""
    try:
        transaction = Share_Sell.objects.get(id=transaction_id, user=request.user)
    except Share_Sell.DoesNotExist:
        messages.error(request, 'Transaction not found.')
        return redirect('sharehub_portfolio')
    
    if request.method == 'POST':
        try:
            from datetime import datetime
            
            # Get form data
            units_sold = int(request.POST.get('units_sold', transaction.units_sold))
            selling_price = Decimal(str(request.POST.get('selling_price', transaction.selling_price)))
            transaction_date = request.POST.get('transaction_date')
            
            # Validate input
            if units_sold <= 0:
                raise ValueError("Units sold must be greater than 0")
            if selling_price <= 0:
                raise ValueError("Selling price must be greater than 0")
            
            # Parse date
            if transaction_date:
                transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
            else:
                transaction_date = transaction.transaction_date
            
            # Update transaction
            transaction.units_sold = units_sold
            transaction.selling_price = selling_price
            transaction.transaction_date = transaction_date
            transaction.save()
            
            messages.success(request, f'Sell transaction updated successfully for {transaction.share.scrip}.')
            return redirect('sharehub_holding_detail', scrip=transaction.share.scrip)
            
        except (ValueError, TypeError) as e:
            messages.error(request, f'Invalid input: {e}')
        except Exception as e:
            messages.error(request, f'Error updating transaction: {e}')
    
    # GET request - show edit form
    context = {
        'transaction': transaction,
        'scrip': transaction.share.scrip,
    }
    return render(request, 'edit_sell_transaction.html', context)


@login_required
def delete_buy_transaction(request, transaction_id):
    """Delete a buy transaction"""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('sharehub_portfolio')
    
    try:
        transaction = Share_Buy.objects.get(id=transaction_id, user=request.user)
        scrip = transaction.scrip
        
        # Check if this transaction has any associated sell transactions
        associated_sells = Share_Sell.objects.filter(share=transaction)
        if associated_sells.exists():
            messages.error(request, 
                f'Cannot delete this purchase transaction because it has associated sell transactions. '
                f'Please delete the sell transactions first.')
            return redirect('sharehub_holding_detail', scrip=scrip)
        
        # Delete the transaction
        transaction.delete()
        messages.success(request, f'Purchase transaction deleted successfully for {scrip}.')
        
        # Redirect to portfolio or holding detail based on redirect_to parameter
        redirect_to = request.POST.get('redirect_to', '')
        if 'holding_detail' in redirect_to:
            return redirect('sharehub_holding_detail', scrip=scrip)
        else:
            return redirect('sharehub_portfolio')
            
    except Share_Buy.DoesNotExist:
        messages.error(request, 'Transaction not found.')
        return redirect('sharehub_portfolio')
    except Exception as e:
        messages.error(request, f'Error deleting transaction: {e}')
        return redirect('sharehub_portfolio')


@login_required
def delete_sell_transaction(request, transaction_id):
    """Delete a sell transaction"""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('sharehub_portfolio')
    
    try:
        transaction = Share_Sell.objects.get(id=transaction_id, user=request.user)
        scrip = transaction.share.scrip
        
        # Restore the units to the original buy transaction
        buy_transaction = transaction.share
        buy_transaction.remaining_units += transaction.units_sold
        buy_transaction.save()
        
        # Delete the sell transaction
        transaction.delete()
        messages.success(request, f'Sell transaction deleted successfully for {scrip}.')
        
        # Redirect to portfolio or holding detail based on redirect_to parameter
        redirect_to = request.POST.get('redirect_to', '')
        if 'holding_detail' in redirect_to:
            return redirect('sharehub_holding_detail', scrip=scrip)
        else:
            return redirect('sharehub_portfolio')
            
    except Share_Sell.DoesNotExist:
        messages.error(request, 'Transaction not found.')
        return redirect('sharehub_portfolio')
    except Exception as e:
        messages.error(request, f'Error deleting transaction: {e}')
        return redirect('sharehub_portfolio')


@login_required
def fee_breakdown_view(request, scrip=None):
    """View for displaying detailed fee breakdown for a specific scrip or transaction"""
    user_purchases = Share_Buy.objects.filter(user=request.user).order_by('-transaction_date', '-id')
    user_sales = Share_Sell.objects.filter(user=request.user).order_by('-transaction_date', '-id')
    
    # Filter by scrip if provided
    if scrip:
        user_purchases = user_purchases.filter(scrip=scrip)
        user_sales = user_sales.filter(share__scrip=scrip)
    
    # Get NEPSE data for current prices
    from .nepse_api_utils import fetch_nepse_stocks_and_ltp
    nepse_stocks = fetch_nepse_stocks_and_ltp()
    nepse_ltp_map = {stock['symbol']: stock for stock in nepse_stocks}
    
    # Calculate fee breakdown for buy transactions
    buy_transactions = []
    total_buy_sebon_fee = Decimal('0')
    total_buy_dp_charge = Decimal('0')
    total_buy_commission = Decimal('0')
    total_buy_amount = Decimal('0')
    
    for purchase in user_purchases:
        costs = purchase.calculate_costs()
        buy_transactions.append({
            'transaction': purchase,
            'costs': costs,
            'current_ltp': nepse_ltp_map.get(purchase.scrip, {}).get('ltp', 0)
        })
        total_buy_sebon_fee += costs['sebon_fee']
        total_buy_dp_charge += costs['dp_charge']
        total_buy_commission += costs['broker_commission']
        total_buy_amount += costs['total_amount']
    
    # Calculate fee breakdown for sell transactions - Group by transaction_group to show original user actions
    sell_transactions = []
    total_sell_sebon_fee = Decimal('0')
    total_sell_dp_charge = Decimal('0')
    total_sell_commission = Decimal('0')
    total_sell_cgt = Decimal('0')
    total_sell_amount = Decimal('0')
    
    # Group sell transactions by transaction_group to show original user transactions
    from collections import defaultdict
    grouped_sells = defaultdict(list)
    
    for transaction in user_sales:
        # If transaction_group exists, use it; otherwise group by date and price (for old data)
        group_key = transaction.transaction_group if transaction.transaction_group else f"{transaction.transaction_date}_{transaction.selling_price}"
        grouped_sells[group_key].append(transaction)
    
    # Process each group as a single original transaction
    for group_key, transactions in grouped_sells.items():
        # Calculate totals for this group (original user transaction)
        total_units_sold = sum(t.units_sold for t in transactions)
        selling_price = transactions[0].selling_price  # Same for all in group
        transaction_date = transactions[0].transaction_date  # Same for all in group
        
        # Calculate total buy cost using the overall WACC (not individual transaction WACCs)
        if scrip:
            # For scrip-specific view, calculate WACC for this scrip
            scrip_purchases = user_purchases
            total_cost = sum(purchase.calculate_costs()['total_amount'] for purchase in scrip_purchases)
            total_units = sum(purchase.units for purchase in scrip_purchases)
            wacc_for_scrip = total_cost / total_units if total_units > 0 else Decimal('0')
            total_buy_cost = wacc_for_scrip * total_units_sold
        else:
            # For all transactions view, use individual transaction WACC
            total_buy_cost = sum(t.calculate_profit_loss()['total_buy_cost'] for t in transactions)
        
        # Calculate fees for the ORIGINAL transaction (not summing split fees)
        total_gross_sale = selling_price * total_units_sold
        
        # Calculate fees based on the original total gross sale
        sebon_fee = total_gross_sale * Decimal('0.00015')
        dp_charge = Decimal('25.00')  # DP charge is fixed per transaction, not per split
        
        # Broker commission calculation based on total gross sale
        if total_gross_sale <= 50000:
            broker_rate = Decimal('0.36')
        elif total_gross_sale <= 500000:
            broker_rate = Decimal('0.33')
        elif total_gross_sale <= 2000000:
            broker_rate = Decimal('0.31')
        elif total_gross_sale <= 10000000:
            broker_rate = Decimal('0.27')
        else:
            broker_rate = Decimal('0.24')
            
        broker_commission = total_gross_sale * (broker_rate / 100)
        net_sale = total_gross_sale - sebon_fee - dp_charge - broker_commission
        
        # Calculate profit/loss with correct WACC-based buy cost
        profit_before_tax = net_sale - total_buy_cost
        
        # Calculate tax based on the representative transaction's holding period
        representative_transaction = transactions[0]
        holding_period_days = (transaction_date - representative_transaction.share.transaction_date).days
        
        # Tax calculation
        tax_amount = Decimal('0')
        if profit_before_tax > 0:
            if holding_period_days >= 365:  # 1 year or more
                tax_amount = profit_before_tax * Decimal('0.05')  # 5% for long-term
            else:  # Less than 1 year
                tax_amount = profit_before_tax * Decimal('0.075')  # 7.5% for short-term
        
        final_profit = profit_before_tax - tax_amount
        receivable_amount = net_sale - tax_amount
        
        # Create a grouped transaction object
        class GroupedSellTransaction:
            def __init__(self, transactions, total_units_sold, selling_price, transaction_date):
                self.transactions = transactions
                self.units_sold = total_units_sold
                self.selling_price = selling_price
                self.transaction_date = transaction_date
                self.share = transactions[0].share
                self.transaction_group = transactions[0].transaction_group
                
            def get_broker_rate(self):
                total_amount = self.units_sold * self.selling_price
                if total_amount <= 50000:
                    return 0.36
                elif total_amount <= 500000:
                    return 0.33
                elif total_amount <= 2000000:
                    return 0.31
                elif total_amount <= 10000000:
                    return 0.27
                else:
                    return 0.24
        
        grouped_transaction = GroupedSellTransaction(transactions, total_units_sold, selling_price, transaction_date)
        
        # Create costs and P&L data
        costs = {
            'sebon_fee': sebon_fee,
            'dp_charge': dp_charge,
            'broker_commission': broker_commission,
            'capital_gains_tax': tax_amount,
            'net_amount': receivable_amount
        }
        
        pnl = {
            'gross_sale': total_gross_sale,
            'sebon_fee': sebon_fee,
            'dp_charge': dp_charge,
            'broker_commission': broker_commission,
            'net_sale': net_sale,
            'receivable_amount': receivable_amount,
            'total_buy_cost': total_buy_cost,
            'profit_before_tax': profit_before_tax,
            'tax_amount': tax_amount,
            'final_profit': final_profit,
            'holding_period_days': holding_period_days,
            'tax_rate': Decimal('0.05') if holding_period_days >= 365 else Decimal('0.075'),
            'tax_rate_percentage': 5 if holding_period_days >= 365 else 7.5,
            'wacc': wacc_for_scrip if scrip else sum(t.calculate_profit_loss()['wacc'] * t.units_sold for t in transactions) / total_units_sold,
            'original_count': len(transactions),  # Number of original FIFO splits
        }
        
        sell_transactions.append({
            'transaction': grouped_transaction,
            'costs': costs,
            'pnl': pnl,
            'current_ltp': nepse_ltp_map.get(grouped_transaction.share.scrip, {}).get('ltp', 0)
        })
        
        # Add to totals
        total_sell_sebon_fee += sebon_fee
        total_sell_dp_charge += dp_charge
        total_sell_commission += broker_commission
        total_sell_cgt += tax_amount
        total_sell_amount += receivable_amount
    
    # Sort sell transactions by date (newest first)
    sell_transactions.sort(key=lambda x: x['transaction'].transaction_date, reverse=True)
    
    # Calculate summary data for the scrip
    if scrip:
        # Calculate total units and remaining units for this scrip
        total_units_bought = sum(purchase.units for purchase in user_purchases)
        total_units_sold = sum(sale.units_sold for sale in user_sales)
        remaining_units = total_units_bought - total_units_sold
        
        # Calculate WACC (Weighted Average Cost of Capital)
        total_cost = sum(purchase.calculate_costs()['total_amount'] for purchase in user_purchases)
        wacc = total_cost / total_units_bought if total_units_bought > 0 else 0
        
        # Get current LTP for this scrip
        current_ltp = nepse_ltp_map.get(scrip, {}).get('ltp', 0)
        
        # Calculate total investment (remaining cost basis)
        total_investment = wacc * remaining_units if remaining_units > 0 else 0
    else:
        # For all transactions view, calculate overall totals
        total_units_bought = sum(purchase.units for purchase in Share_Buy.objects.filter(user=request.user))
        total_units_sold = sum(sale.units_sold for sale in Share_Sell.objects.filter(user=request.user))
        remaining_units = total_units_bought - total_units_sold
        wacc = 0  # Can't calculate meaningful WACC across different scrips
        current_ltp = 0
        total_investment = total_buy_amount - total_sell_amount
    
    # Calculate totals
    total_fees = {
        'total_sebon_fee': total_buy_sebon_fee + total_sell_sebon_fee,
        'total_dp_charge': total_buy_dp_charge + total_sell_dp_charge,
        'total_commission': total_buy_commission + total_sell_commission,
        'total_cgt': total_sell_cgt,
        'total_buy_amount': total_buy_amount,
        'total_sell_amount': total_sell_amount,
        'net_investment': total_buy_amount - total_sell_amount
    }
    
    context = {
        'scrip': scrip,
        'buy_transactions': buy_transactions,
        'sell_transactions': sell_transactions,
        'total_fees': total_fees,
        'nepse_ltp_map': nepse_ltp_map,
        'title': f'Fee Breakdown - {scrip}' if scrip else 'Fee Breakdown - All Transactions',
        'total_units': total_units_bought,
        'remaining_units': remaining_units,
        'wacc': wacc,
        'total_investment': total_investment,
        'current_ltp': current_ltp
    }
    
    return render(request, 'fee_breakdown.html', context)


# Custom Error Handlers
def custom_404(request, exception):
    """Custom 404 error handler"""
    return render(request, '404.html', status=404)


def custom_500(request):
    """Custom 500 error handler"""
    return render(request, '500.html', status=500)