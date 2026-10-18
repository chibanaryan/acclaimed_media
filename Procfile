web: gunicorn acclaimedgames.wsgi --workers 2 --timeout 600 --graceful-timeout 30 --max-requests 500 --max-requests-jitter 50
release: python manage.py migrate && python manage.py createcachetable cache_table
