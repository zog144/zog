"""Create one initial administrator; never reset an existing account on startup."""
import os
from pathlib import Path
import secrets
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from zog.station_access.services.locks import workspace_lock


class Command(BaseCommand):
    help = 'Initialize one administrator with a generated password and a private first-login file.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='station-admin')

    def handle(self, *args, **options):
        with workspace_lock('initial-administrator'):
            User = get_user_model()
            if User.objects.exists():
                self.stdout.write('Existing accounts preserved; no password or permissions changed.')
                return
            password = secrets.token_urlsafe(32)
            path = Path(settings.STATE_DIRECTORY) / 'FIRST-LOGIN.txt'
            text = (f'Station-access initial login\nUsername: {options["username"]}\nPassword: {password}\n\n'
                    'Use these credentials at the station-access login page.\n'
                    'This file contains the initial password; the database stores its Django password hash.\n'
                    'Existing accounts are never reset by initialization.\n')
            # Write the handoff first, then create the account. A failed transaction leaves
            # no active account; a subsequent initialization replaces this handoff.
            with open(path, 'w', encoding='utf-8', opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
                os.chmod(path, 0o600)
                handle.write(text); handle.flush(); os.fsync(handle.fileno())
            with transaction.atomic():
                User.objects.create_superuser(username=options['username'], password=password)
            self.stdout.write(f'Initial administrator created. Credentials: {path}')
