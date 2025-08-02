from django.urls import path
from authentication import views

urlpatterns = [
    path('', views.index, name='home'),
    path('dashboard/', views.index, name='dashboard'),
    path('portfolio/', views.sharehub_portfolio_view, name='sharehub_portfolio'),
    path('holding/<str:scrip>/', views.sharehub_holding_detail_view, name='sharehub_holding_detail'),
    path('sold/<str:scrip>/', views.sharehub_sold_holding_detail_view, name='sharehub_sold_detail'),
    path('fee-breakdown/', views.fee_breakdown_view, name='fee_breakdown'),
    path('fee-breakdown/<str:scrip>/', views.fee_breakdown_view, name='fee_breakdown_scrip'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('verify/<str:token>/', views.verify, name='verify'),
    path('password-reset/', views.password_reset_request_view, name='password_reset_request'),
    path('password-reset-confirm/<uidb64>/<token>/', views.password_reset_confirm_view, name='password_reset_confirm'),
    path('buy-shares/', views.share_buy_view, name='share_buy'),
    path('sell-shares/', views.share_sell_view, name='share_sell'),
    path('fetch-tms-data/', views.fetch_tms_data_view, name='fetch_tms_data'),
 
]
