from django.contrib import admin
from .models import Profile_ver, Share_Buy, Share_Sell,NepseStock,TMSConfiguration

admin.site.register(NepseStock)
admin.site.register(TMSConfiguration)
@admin.register(Profile_ver)
class ProfileVerAdmin(admin.ModelAdmin):
    list_display = ['user', 'uid', 'is_verified']
    list_filter = ['is_verified']
    search_fields = ['user__username', 'uid']

@admin.register(Share_Buy)
class ShareBuyAdmin(admin.ModelAdmin):
    list_display = ['scrip', 'units', 'buying_price', 'transaction_date', 'remaining_units', 'availability_status']
    list_filter = ['transaction_date', 'scrip', 'remaining_units']
    search_fields = ['scrip']
    date_hierarchy = 'transaction_date'
    
    def availability_status(self, obj):
        return obj.availability_status
    availability_status.short_description = 'Status'


@admin.register(Share_Sell)
class ShareSellAdmin(admin.ModelAdmin):
    list_display = ['scrip', 'share', 'units_sold', 'selling_price', 'transaction_date']
    list_filter = ['transaction_date', 'share__scrip']
    search_fields = ['share__scrip']
    date_hierarchy = 'transaction_date'
    
    def scrip(self, obj):
        """Display the scrip name"""
        return obj.share.scrip
    scrip.short_description = 'Scrip'
    scrip.admin_order_field = 'share__scrip'  # Allows sorting by scrip
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Only show shares that have remaining units available for sale"""
        if db_field.name == "share":
            kwargs["queryset"] = Share_Buy.objects.filter(remaining_units__gt=0).order_by('scrip', 'transaction_date')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
