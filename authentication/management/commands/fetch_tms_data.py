from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from authentication.tms_service import fetch_tms_data


class Command(BaseCommand):
    help = 'Fetch share data from TMS Nepse website using manual login'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, required=True, help='Django user ID to associate the data with')
        parser.add_argument('--tms-number', type=int, help='TMS server number (uses profile setting if not provided)')

    

    def handle(self, *args, **options):
        try:
            user = User.objects.get(id=options['user_id'])
            
            self.stdout.write(
                self.style.SUCCESS(f'Starting TMS data fetch for user: {user.username}')
            )
            
            tms_number = options.get('tms_number')
            if not tms_number:
                try:
                    tms_number = user.profile_ver.tms_server_number
                    self.stdout.write(f'Using TMS server from profile: {tms_number}')
                except:
                    tms_number = 52
                    self.stdout.write(f'Using default TMS server: {tms_number}')
            
            self.stdout.write(
                self.style.WARNING(
                    'A browser window will open. Please login to TMS manually with your credentials and captcha.'
                )
            )
            
            result = fetch_tms_data(
                user=user,
                tms_number=tms_number
            )
            
            if result['success']:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully fetched {result["records_found"]} records, '
                        f'saved {result["records_saved"]} new records'
                    )
                )
                
                for record in result['data']:
                    self.stdout.write(
                        f'  - {record.scrip}: {record.units} units @ Rs.{record.buying_price}'
                    )
            else:
                self.stdout.write(
                    self.style.ERROR(f'Failed to fetch data: {result["error"]}')
                )
                
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User with ID {options["user_id"]} not found')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error: {str(e)}')
            )