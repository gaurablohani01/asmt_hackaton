# NEPSE Portfolio Management System

A Django-based web application for managing NEPSE (Nepal Stock Exchange) portfolio, tracking investments, and analyzing stock performance.

## Features

- 🔐 **User Authentication**: Secure login/register with email verification
- 📊 **Portfolio Management**: Track buy/sell transactions and calculate profits/losses
- 📈 **Stock Data Integration**: Real-time NEPSE stock data fetching
- 💰 **Investment Analysis**: WACC calculation, profit/loss tracking
- 🔒 **TMS Integration**: Connect with TMS (Trading Management System)
- 📱 **Responsive Design**: Modern UI with glassmorphism styling
- 🛡️ **Security**: Environment-based configuration for sensitive data

## Tech Stack

- **Backend**: Django 5.2.4
- **Database**: SQLite (development)
- **Frontend**: HTML, CSS, JavaScript
- **Email**: SMTP integration for notifications
- **Web Automation**: Playwright for TMS data fetching
- **Security**: Environment variables with python-dotenv

## Installation

### Prerequisites

- Python 3.8+
- Git

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/gaurablohani01/asian-hackaton.git
   cd asian-hackaton
   ```

2. **Create virtual environment**
   ```bash
   python -m venv myenv
   source myenv/bin/activate  # On Windows: myenv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers**
   ```bash
   playwright install
   ```

5. **Environment Configuration**
   
   Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   
   Update `.env` with your credentials:
   ```env
   SECRET_KEY=your-secret-key-here
   DEBUG=True
   ALLOWED_HOSTS=localhost,127.0.0.1
   
   EMAIL_HOST_USER=your-email@gmail.com
   EMAIL_HOST_PASSWORD=your-app-password
   ```

6. **Database Migration**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

7. **Create Superuser** (Optional)
   ```bash
   python manage.py createsuperuser
   ```

8. **Run the Development Server**
   ```bash
   python manage.py runserver
   ```

   Visit `http://127.0.0.1:8000/` in your browser.

## Project Structure

```
hackaton_project/
├── authentication/          # Main Django app
│   ├── models.py           # Database models
│   ├── views.py            # View functions
│   ├── forms.py            # Django forms
│   ├── urls.py             # URL patterns
│   ├── templates/          # HTML templates
│   └── management/         # Custom management commands
├── project/                # Django project settings
│   ├── settings.py         # Project configuration
│   └── urls.py             # Root URL configuration
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── .gitignore            # Git ignore rules
└── README.md             # This file
```

## Key Features Explained

### Portfolio Management
- Track share purchases and sales
- Calculate WACC (Weighted Average Cost of Capital)
- Monitor profit/loss for individual stocks
- View comprehensive portfolio overview

### TMS Integration
- Automated data fetching from TMS platform
- Secure credential management
- Real-time transaction synchronization

### NEPSE Data
- Live stock price updates
- Market data integration
- Stock symbol validation

### Security Features
- Environment-based configuration
- Secure session management
- CSRF protection
- XSS filtering
- HTTPS enforcement (production)

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Django secret key | Yes |
| `DEBUG` | Debug mode (True/False) | Yes |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | Yes |
| `EMAIL_HOST_USER` | Email username | Yes |
| `EMAIL_HOST_PASSWORD` | Email app password | Yes |
| `EMAIL_HOST` | SMTP server | No (default: smtp.gmail.com) |
| `EMAIL_PORT` | SMTP port | No (default: 587) |

## Usage

1. **Register/Login**: Create an account or login with existing credentials
2. **Dashboard**: View your portfolio overview and recent transactions
3. **Add Transactions**: Record buy/sell transactions manually
4. **TMS Sync**: Connect your TMS account for automatic data fetching
5. **Portfolio Analysis**: View detailed profit/loss analysis and WACC calculations

## Development

### Running Tests
```bash
python manage.py test
```

### Custom Management Commands
```bash
# Fetch TMS data
python manage.py fetch_tms_data
```

### Code Style
- Follow PEP 8 guidelines
- Use meaningful variable names
- Add docstrings for functions and classes

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Security Notes

- Never commit `.env` files to the repository
- Use strong passwords and app-specific passwords for email
- Keep dependencies updated
- Set `DEBUG=False` in production
- Use HTTPS in production

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For support, email gaurablohani01@gmail.com or create an issue on GitHub.

## Acknowledgments

- Nepal Stock Exchange (NEPSE) for market data
- TMS platform for trading integration
- Django community for the excellent framework

---

**Note**: This project is for educational and personal use. Please ensure compliance with NEPSE and TMS terms of service when using their data and services.
# asmt_hackaton
# codebulls
