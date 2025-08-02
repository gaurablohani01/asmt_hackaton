from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

class Profile_ver(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    uid = models.CharField(max_length=100)
    is_verified = models.BooleanField(default=False)
    
    # TMS Configuration - Only store server number, credentials handled in session
    tms_server_number = models.IntegerField(default=52, help_text="TMS server number (51, 52, 53, 54)")
    tms_configured = models.BooleanField(default=False, help_text="Whether user has configured TMS access")
    last_tms_sync = models.DateTimeField(null=True, blank=True, help_text="Last successful TMS data sync")
    
    def __str__(self):
        return f'{self.user.username} - {"Verified" if self.is_verified else "Unverified"} (TMS: {self.tms_server_number})'
    
    @property
    def tms_login_url(self):
        """Get the TMS login URL based on server number"""
        return f"https://tms{self.tms_server_number}.nepsetms.com.np/login"
    
    @property
    def tms_settlement_url(self):
        """Get the TMS settlement URL based on server number"""
        return f"https://tms{self.tms_server_number}.nepsetms.com.np/tms/me/gen-bank/settlement-buy-info#PaymentDue"


class TMSConfiguration(models.Model):
    """System-level TMS configuration for reference only - No credentials stored"""
    name = models.CharField(max_length=100, help_text="Configuration name")
    tms_server = models.IntegerField(default=52)
    server_description = models.CharField(max_length=200, blank=True, help_text="Description of this TMS server")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"TMS{self.tms_server} - {self.name} ({'Active' if self.is_active else 'Inactive'})"
    
    @property
    def login_url(self):
        """Get the TMS login URL for this server"""
        return f"https://tms{self.tms_server}.nepsetms.com.np/login"


class NepseStock(models.Model):
    """Model to store real-time Nepse stock data"""
    symbol = models.CharField(max_length=20, unique=True, help_text="Stock symbol (e.g., MHL, NABIL)")
    name = models.CharField(max_length=200, help_text="Full company name")
    sector = models.CharField(max_length=100, blank=True, null=True)
    last_traded_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    market_cap = models.BigIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['symbol']
    
    def __str__(self):
        return f"{self.symbol} - {self.name}"


class Share_Buy(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='share_purchases')
    scrip = models.CharField(max_length=20)
    units = models.PositiveIntegerField()
    buying_price = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_date = models.DateField()  
    remaining_units = models.PositiveIntegerField(default=0) 

    def save(self, *args, **kwargs):
        if not self.pk:  # New record
            self.remaining_units = self.units
        super().save(*args, **kwargs)

    def get_broker_rate(self):  
        total_amount = self.units * self.buying_price
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

    def calculate_costs(self): 
        total_amount = self.units * self.buying_price
        sebon_fee = total_amount * Decimal('0.00015')
        dp_charge = Decimal('25')
        broker_commission = total_amount * (Decimal(str(self.get_broker_rate())) / Decimal('100'))
        total_cost = total_amount + sebon_fee + dp_charge + broker_commission
        cost_per_share = total_cost / self.units
        total_amount = cost_per_share*self.units
        
        return {
            'sebon_fee': sebon_fee,
            'dp_charge': dp_charge,
            'broker_commission': broker_commission,
            'cost_per_share': cost_per_share,
            'total_amount': total_amount,
        }

    @property
    def availability_status(self):
        """Show if shares are available for selling"""
        if self.remaining_units > 0:
            return f"Available: {self.remaining_units} units"
        else:
            return "Fully sold"

    def __str__(self):
        return f"{self.scrip} - {self.units} units @ Rs.{self.buying_price} (Available: {self.remaining_units})"


class Share_Sell(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='share_sales')
    share = models.ForeignKey(Share_Buy, on_delete=models.CASCADE)
    units_sold = models.PositiveIntegerField()
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_date = models.DateField()
    transaction_group = models.CharField(max_length=100, null=True, blank=True, help_text="Groups sell records from the same user transaction") 

    @classmethod
    def get_available_shares(cls, user):
        """Get all shares that have remaining units available for selling for a specific user"""
        return Share_Buy.objects.filter(user=user, remaining_units__gt=0).order_by('scrip', 'transaction_date')

    @classmethod
    def get_available_scrips(cls, user):
        """Get list of unique scrips that have units available for selling for a specific user"""
        return Share_Buy.objects.filter(user=user, remaining_units__gt=0).values_list('scrip', flat=True).distinct().order_by('scrip')

    def clean(self):
        """Validate the sale before saving"""
        if self.share and self.units_sold:
            if self.units_sold > self.share.remaining_units:
                raise ValueError(f"Cannot sell {self.units_sold} units. Only {self.share.remaining_units} units available for {self.share.scrip}")

    def save(self, *args, **kwargs):
        if not self.pk:  
            if self.share.remaining_units >= self.units_sold:
                self.share.remaining_units -= self.units_sold
                self.share.save()
            else:
                raise ValueError(f"Not enough units. Available: {self.share.remaining_units}")
        super().save(*args, **kwargs)

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

    def calculate_profit_loss(self):
        scrip = self.share.scrip
        user = self.share.user
        all_buys = Share_Buy.objects.filter(user=user, scrip=scrip)
        
        total_cost = Decimal('0')
        total_units = 0
        for buy in all_buys:
            costs = buy.calculate_costs()
            total_cost += costs['total_amount']
            total_units += buy.units
        
        wacc = total_cost / total_units if total_units > 0 else Decimal('0')
        total_buy_amount = wacc * self.units_sold
        
        gross_sale = self.units_sold * self.selling_price
        sebon_fee = gross_sale * Decimal('0.00015')
        dp_charge = Decimal('25')
        broker_commission = gross_sale * (Decimal(str(self.get_broker_rate())) / Decimal('100'))
        net_sale = gross_sale - sebon_fee - dp_charge - broker_commission
        
        profit_before_tax = net_sale - total_buy_amount
        
        tax_amount = Decimal('0')
        holding_period_days = (self.transaction_date - self.share.transaction_date).days
        
        if profit_before_tax > 0:
            if holding_period_days >= 365:  
                tax_amount = profit_before_tax * Decimal('0.05') 
            else:  
                tax_amount = profit_before_tax * Decimal('0.075')  
        
        final_profit = profit_before_tax - tax_amount
        receivable_amount = net_sale - tax_amount 
        
        return {
            'gross_sale': gross_sale,
            'sebon_fee': sebon_fee,
            'dp_charge': dp_charge,
            'broker_commission': broker_commission,
            'net_sale': net_sale,
            'receivable_amount': receivable_amount, 
            'total_buy_cost': total_buy_amount,
            'profit_before_tax': profit_before_tax,
            'tax_amount': tax_amount,
            'final_profit': final_profit,
            'holding_period_days': holding_period_days,
            'tax_rate': Decimal('0.05') if holding_period_days >= 365 else Decimal('0.075'),
            'tax_rate_percentage': 5 if holding_period_days >= 365 else 7.5,  # Add percentage for templates
            'wacc': wacc,  # Add WACC for reference
        }

    def calculate_costs(self):
        """
        Calculate the costs associated with this sell transaction.
        Returns costs in similar format to Share_Buy.calculate_costs() for consistency.
        """
        gross_sale = self.units_sold * self.selling_price
        sebon_fee = gross_sale * Decimal('0.00015')
        dp_charge = Decimal('25')
        broker_commission = gross_sale * (Decimal(str(self.get_broker_rate())) / Decimal('100'))
        
        # Calculate capital gains tax
        holding_period_days = (self.transaction_date - self.share.transaction_date).days
        
        # Get the weighted average cost for this sale
        scrip = self.share.scrip
        user = self.share.user
        all_buys = Share_Buy.objects.filter(user=user, scrip=scrip)
        
        total_cost = Decimal('0')
        total_units = 0
        for buy in all_buys:
            costs = buy.calculate_costs()
            total_cost += costs['total_amount']
            total_units += buy.units
        
        wacc = total_cost / total_units if total_units > 0 else Decimal('0')
        total_buy_amount = wacc * self.units_sold
        
        profit_before_tax = gross_sale - sebon_fee - dp_charge - broker_commission - total_buy_amount
        
        capital_gains_tax = Decimal('0')
        if profit_before_tax > 0:
            if holding_period_days >= 365:  
                capital_gains_tax = profit_before_tax * Decimal('0.05') 
            else:  
                capital_gains_tax = profit_before_tax * Decimal('0.075')
        
        net_amount = gross_sale - sebon_fee - dp_charge - broker_commission - capital_gains_tax
        
        return {
            'sebon_fee': sebon_fee,
            'dp_charge': dp_charge,
            'broker_commission': broker_commission,
            'capital_gains_tax': capital_gains_tax,
            'gross_amount': gross_sale,
            'net_amount': net_amount,
            'total_amount': net_amount,  # For consistency with Share_Buy.calculate_costs()
        }

    @property
    def scrip(self):
        """Get the scrip name from the related Share_Buy"""
        return self.share.scrip

    def __str__(self):
        return f"Sell {self.units_sold} units of {self.share.scrip} @ Rs.{self.selling_price}"