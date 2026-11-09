web: gunicorn acclaimedgames.wsgi --worker-class gthread --workers 2 --threads 3 --timeout 600 --graceful-timeout 30 --max-requests 2000 --max-requests-jitter 200
release: python manage.py migrate && python manage.py createcachetable cache_table
