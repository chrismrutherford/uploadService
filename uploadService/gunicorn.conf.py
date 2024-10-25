bind = "0.0.0.0:5003"
worker_class = "gevent"
workers = 1
#daemon=True
#threads = 1024
pidfile = 'pidfile'
errorlog = '-'
loglevel = 'info'
accesslog = '-'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

certfile = ''
keyfile = ''

